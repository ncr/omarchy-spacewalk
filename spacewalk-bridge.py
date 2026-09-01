#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["bleak>=0.22"]
# ///
"""Most między bieżnią (Bluetooth, FTMS) a pluginem Omarchy.

Na stdout leci po jednym obiekcie JSON na linię:

    {"t":"status","state":"connected","device":"..."}
    {"t":"data","speed":2.5,"incline":3.0,"distance_m":1840,"kcal":62,
     "elapsed_s":1620,"steps":2705,"day_steps":7412,...}
    {"t":"error","msg":"..."}

Ze stdin czyta po jednej komendzie na linię:

    start | stop | pause | speed 2.5 | incline 3 | reset-day | ping
"""

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

FTMS_SERVICE = "00001826-0000-1000-8000-00805f9b34fb"
TREADMILL_DATA = "00002acd-0000-1000-8000-00805f9b34fb"
CONTROL_POINT = "00002ad9-0000-1000-8000-00805f9b34fb"
MACHINE_STATUS = "00002ada-0000-1000-8000-00805f9b34fb"

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "omarchy-spacewalk"

# Kody operacji punktu sterowania (FTMS 4.16.1)
OP_REQUEST_CONTROL = 0x00
OP_RESET = 0x01
OP_SET_SPEED = 0x02
OP_SET_INCLINATION = 0x03
OP_START = 0x07
OP_STOP = 0x08
RESPONSE_CODE = 0x80
RESULT_SUCCESS = 0x01

RESULT_NAMES = {
    0x01: "przyjęte",
    0x02: "nieobsługiwane",
    0x03: "zły parametr",
    0x04: "odrzucone",
    0x05: "brak sterowania",
}


LOG_PATH = STATE_DIR / "bridge.log"
SESSIONS_PATH = STATE_DIR / "sessions.jsonl"

# Po tylu sekundach bez ruchu uznajemy przejście za skończone. Bieżnia
# zatrzymuje się sama, gdy nikt na niej nie stoi, więc krótka przerwa na
# poprawienie czegoś przy biurku nie powinna dzielić marszu na dwie sesje.
SESSION_IDLE_GAP = 90


def emit(obj):
    line = json.dumps(obj, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    # Kopia do pliku: stdout mostu czyta shell, więc bez tego nie da się
    # zajrzeć, co bieżnia mówi, gdy plugin działa.
    try:
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        with LOG_PATH.open("a") as fh:
            fh.write(f"{datetime.now().isoformat(timespec='seconds')} {line}\n")
    except OSError:
        pass


def status(state, **extra):
    emit({"t": "status", "state": state, **extra})


def error(msg):
    emit({"t": "error", "msg": str(msg)})


# ---------------------------------------------------------------- dane bieżni

def parse_treadmill_data(data: bytes) -> dict:
    """Rozbiera pakiet Treadmill Data (0x2ACD).

    Pierwsze dwa bajty to flagi; każde pole jest obecne tylko wtedy, gdy jego bit
    to mówi, a pola idą w kolejności z tabeli 4.9.1.1 specyfikacji FTMS. Bit 0 jest
    odwrócony: 0 znaczy „prędkość chwilowa jest w pakiecie".
    """
    if len(data) < 2:
        return {}
    flags = int.from_bytes(data[0:2], "little")
    pos = 2
    out = {}

    def take(width, signed=False):
        nonlocal pos
        if pos + width > len(data):
            raise ValueError("pakiet krótszy niż wynika z flag")
        value = int.from_bytes(data[pos:pos + width], "little", signed=signed)
        pos += width
        return value

    try:
        if not (flags & 0x0001):                      # bit 0: More Data
            out["speed"] = take(2) / 100.0            # km/h
        if flags & 0x0002:
            out["avg_speed"] = take(2) / 100.0
        if flags & 0x0004:
            out["distance_m"] = take(3)
        if flags & 0x0008:
            out["incline"] = take(2, signed=True) / 10.0     # %
            out["ramp_angle"] = take(2, signed=True) / 10.0  # stopnie
        if flags & 0x0010:
            out["elevation_pos_m"] = take(2) / 10.0
            out["elevation_neg_m"] = take(2) / 10.0
        if flags & 0x0020:
            out["pace"] = take(1)
        if flags & 0x0040:
            out["avg_pace"] = take(1)
        if flags & 0x0080:
            out["kcal"] = take(2)
            out["kcal_per_hour"] = take(2)
            per_min = take(1)
            out["kcal_per_min"] = None if per_min == 0xFF else per_min
        if flags & 0x0100:
            out["heart_rate"] = take(1)
        if flags & 0x0200:
            out["met"] = take(1) / 10.0
        if flags & 0x0400:
            out["elapsed_s"] = take(2)
        if flags & 0x0800:
            out["remaining_s"] = take(2)
        # Bit 13 nie istnieje w specyfikacji FTMS — Urevo dopisał w tym miejscu
        # licznik kroków (uint24). Sprawdzone na URTM024: 179 kroków na 100 m
        # marszu, podczas gdy czas w tym samym pakiecie rósł równo 1/s.
        if flags & 0x2000:
            out["steps"] = take(3)
    except ValueError as exc:
        error(f"{exc}: flagi 0x{flags:04x}, dane {data.hex(' ')}")

    return out


# ------------------------------------------------------------- dzienny licznik

class DayTotals:
    """Suma dnia: bieżnia zeruje liczniki przy każdym starcie, więc dodajemy
    przyrosty, a nie nadpisujemy sumy."""

    FIELDS = ("steps", "distance_m", "kcal", "elapsed_s")

    def __init__(self):
        self.day = date.today()
        self.totals = {f: 0.0 for f in self.FIELDS}
        self.session = {f: None for f in self.FIELDS}
        self.dirty = False
        self.load()

    @property
    def path(self) -> Path:
        return STATE_DIR / f"{self.day.isoformat()}.json"

    def load(self):
        try:
            raw = json.loads(self.path.read_text())
            for f in self.FIELDS:
                self.totals[f] = float(raw.get(f, 0))
        except FileNotFoundError:
            pass
        except (ValueError, OSError) as exc:
            error(f"nie mogę wczytać {self.path}: {exc}")

    def save(self):
        if not self.dirty:
            return
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            payload = {f: round(self.totals[f], 2) for f in self.FIELDS}
            payload["updated"] = datetime.now().isoformat(timespec="seconds")
            tmp = self.path.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload, indent=2))
            tmp.replace(self.path)
            self.dirty = False
        except OSError as exc:
            error(f"nie mogę zapisać {self.path}: {exc}")

    def roll_over_if_needed(self):
        today = date.today()
        if today == self.day:
            return
        self.save()
        self.day = today
        self.totals = {f: 0.0 for f in self.FIELDS}
        self.session = {f: None for f in self.FIELDS}
        self.load()
        emit({"t": "history", "days": read_history()})

    def update(self, sample: dict):
        """Przyjmuje wartości narastające od początku sesji i dolicza różnicę.

        Dystans, kalorie i czas doliczają się tylko wtedy, gdy w tym samym
        odczycie przybyło kroków. Bieżnia liczy dystans od ruchu pasa, a kroki
        od człowieka — bez tego warunku pusta, kręcąca się taśma dopisywała do
        dnia metry i kalorie, których nikt nie przeszedł (150 m zamiast 30).
        """
        self.roll_over_if_needed()

        deltas = {}
        for f in self.FIELDS:
            if f not in sample or sample[f] is None:
                continue
            value = float(sample[f])
            previous = self.session[f]
            if previous is None:
                # Pierwszy odczyt po starcie albo po połączeniu: nie wiadomo,
                # ile z tego licznika już zaliczyliśmy, więc służy on wyłącznie
                # za punkt odniesienia. Bez tego naciśnięcie Startu doliczało
                # cały licznik poprzedniego przejścia jeszcze raz.
                self.session[f] = value
                deltas[f] = 0.0
                continue
            if value < previous:
                # Bieżnia wyzerowała licznik — liczymy od zera.
                previous = 0.0
            deltas[f] = value - previous
            self.session[f] = value

        if deltas.get("steps", 0) <= 0:
            return {}

        applied = {}
        for f, delta in deltas.items():
            if delta > 0:
                self.totals[f] += delta
                applied[f] = delta
                self.dirty = True
        return applied

    def new_session(self):
        """Kasuje punkt odniesienia, nie zeruje go: dopiero pierwszy odczyt
        powie, od czego liczyć przyrosty."""
        self.session = {f: None for f in self.FIELDS}

    def snapshot(self) -> dict:
        return {
            "day": self.day.isoformat(),
            "day_steps": int(self.totals["steps"]),
            "day_distance_m": int(self.totals["distance_m"]),
            "day_kcal": int(self.totals["kcal"]),
            "day_elapsed_s": int(self.totals["elapsed_s"]),
        }


# ------------------------------------------------------------------- historia

HISTORY_DAYS = 120


def read_history(days: int = HISTORY_DAYS) -> dict:
    """Sumy z ostatnich dni, prosto z plików dnia. Panel rysuje z tego kratkę,
    więc czytamy katalog raz przy starcie, nie przy każdym otwarciu panelu."""
    out = {}
    today = date.today()
    for offset in range(days):
        day = today - timedelta(days=offset)
        path = STATE_DIR / f"{day.isoformat()}.json"
        try:
            raw = json.loads(path.read_text())
        except (FileNotFoundError, ValueError, OSError):
            continue
        out[day.isoformat()] = {
            "steps": int(float(raw.get("steps", 0))),
            "distance_m": int(float(raw.get("distance_m", 0))),
            "kcal": int(float(raw.get("kcal", 0))),
            "elapsed_s": int(float(raw.get("elapsed_s", 0))),
        }
    return out


# --------------------------------------------------------- serwer dla telefonu

def read_sessions() -> list[dict]:
    try:
        lines = SESSIONS_PATH.read_text().splitlines()
    except FileNotFoundError:
        return []
    out = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def write_sessions(records: list[dict]):
    tmp = SESSIONS_PATH.with_suffix(".jsonl.tmp")
    tmp.write_text("".join(json.dumps(r) + "\n" for r in records))
    tmp.replace(SESSIONS_PATH)


def mark_sent(ids: list[str]) -> int:
    records = read_sessions()
    wanted = set(ids)
    changed = 0
    for r in records:
        if r.get("id") in wanted and not r.get("sent"):
            r["sent"] = True
            changed += 1
    if changed:
        write_sessions(records)
    return changed


def tailscale_ip() -> str:
    """Adres tego komputera w tailnecie. Bez niego serwer nie ma się na czym
    postawić tak, żeby telefon go widział, a reszta sieci nie."""
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                             text=True, timeout=5).stdout.strip().splitlines()
        if out:
            return out[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    error("nie znalazłem adresu Tailscale — serwer stanie tylko na localhost")
    return "127.0.0.1"


class PhoneServer:
    """Trzy adresy dla skrótu na iPhonie, po Tailscale:

        GET  /pending   niewysłane przejścia
        POST /ack       {"ids": [...]} — oznacz jako wysłane
        GET  /today     sumy dnia (podgląd)

    Słucha tylko na podanym adresie, domyślnie tym z Tailscale, więc nie
    wystawia niczego do sieci lokalnej ani do internetu.
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        # Co wydało ostatnie /pending — żeby skrót mógł potwierdzić odbiór
        # jednym wywołaniem, bez składania JSON-a z identyfikatorami.
        self.last_served: list[str] = []

    async def handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter):
        try:
            request_line = await asyncio.wait_for(reader.readline(), 5.0)
            if not request_line:
                return
            parts = request_line.decode("latin-1").split()
            if len(parts) < 2:
                return
            method, path = parts[0], parts[1]

            length = 0
            while True:
                header = await asyncio.wait_for(reader.readline(), 5.0)
                if header in (b"\r\n", b"\n", b""):
                    break
                name, _, value = header.decode("latin-1").partition(":")
                if name.strip().lower() == "content-length":
                    length = int(value.strip() or 0)
            body = await reader.readexactly(length) if length else b""

            peer = writer.get_extra_info("peername")
            status_code, payload = self.route(method, path, body)
            emit({"t": "request", "method": method, "path": path,
                  "from": peer[0] if peer else "?", "status": status_code})
            data = json.dumps(payload).encode()
            writer.write(
                f"HTTP/1.1 {status_code}\r\n"
                f"Content-Type: application/json\r\n"
                f"Content-Length: {len(data)}\r\n"
                "Connection: close\r\n\r\n".encode() + data
            )
            await writer.drain()
        except (asyncio.TimeoutError, asyncio.IncompleteReadError, ConnectionError, ValueError):
            pass
        finally:
            writer.close()

    def route(self, method: str, path: str, body: bytes):
        path, _, query = path.partition("?")
        if method == "GET" and path == "/pending":
            pending = [r for r in read_sessions() if not r.get("sent")]
            self.last_served = [r["id"] for r in pending]
            # Skróty na iPhonie nie zamieniają "2026-08-31T12:47:32" na datę
            # same z siebie; ze spacją zamiast T akcja „Uzyskaj datę z tekstu"
            # radzi sobie bez ustawiania formatu.
            for r in pending:
                r["end_text"] = r.get("end", "").replace("T", " ")
                r["start_text"] = r.get("start", "").replace("T", " ")
                r["distance_km"] = round(r.get("distance_m", 0) / 1000, 3)
            return "200 OK", {"sessions": pending}
        if method == "GET" and path == "/ack-all":
            return "200 OK", {"marked": mark_sent(self.last_served)}
        if method == "GET" and path == "/ack":
            ids = [i for i in query.replace("ids=", "").split(",") if i]
            return "200 OK", {"marked": mark_sent(ids)}
        if method == "GET" and path == "/today":
            day = DayTotals()
            return "200 OK", day.snapshot()
        if method == "POST" and path == "/ack":
            try:
                ids = json.loads(body or b"{}").get("ids") or []
            except ValueError:
                return "400 Bad Request", {"error": "zły JSON"}
            return "200 OK", {"marked": mark_sent([str(i) for i in ids])}
        return "404 Not Found", {"error": "nie ma takiego adresu"}

    async def serve(self):
        # Ponawiamy, zamiast się poddać: przy restarcie shella poprzedni most
        # potrafi jeszcze przez chwilę trzymać port, a zakończenie tego zadania
        # ubijało cały most (run() kończy się na pierwszym gotowym zadaniu).
        while True:
            try:
                server = await asyncio.start_server(self.handle, self.host, self.port)
                break
            except OSError as exc:
                error(f"port {self.host}:{self.port} zajęty ({exc}) — ponawiam za 5 s")
                await asyncio.sleep(5.0)
        # Własny typ, nie status: „status" opisuje połączenie z bieżnią i panel
        # bierze go wprost jako stan łącza.
        emit({"t": "server", "address": f"{self.host}:{self.port}"})
        async with server:
            await server.serve_forever()


# ------------------------------------------------------------------ połączenie

class Bridge:
    def __init__(self, address: str | None, steps_uuid: str | None, stride_m: float):
        self.address = address
        self.steps_uuid = steps_uuid
        self.stride_m = stride_m
        self.client: BleakClient | None = None
        self.day = DayTotals()
        self.latest: dict = {}
        self.control_replies: asyncio.Queue = asyncio.Queue()
        self.has_control = False
        self.connected = asyncio.Event()
        self.target_speed: float | None = None
        self.target_incline: float | None = None
        self.session_started_at: datetime | None = None
        self.session_last_move: float = 0.0
        self.session_peak: dict = {}
        self.server: PhoneServer | None = None
        # running | paused | stopped — pauza to zejście z taśmy, stop to komenda
        # albo wyłącznik bezpieczeństwa. Bieżnia rozróżnia jedno od drugiego
        # w statusie maszyny, panel pokazuje to i proponuje wznowienie.
        self.belt_state = "stopped"

    @property
    def running_belt(self) -> bool:
        return self.latest.get("speed", 0) > 0

    # ---- sesje (przejścia) do wysłania na telefon

    def track_session(self, applied: dict):
        """Otwiera przejście przy pierwszym ruchu i zamyka po SESSION_IDLE_GAP
        sekund bezruchu.

        Sumuje te same przyrosty, które idą do licznika dnia — nie wskazania
        bieżni. Wskazania przeżywają restart mostu, więc liczone z nich
        przejście zapisywało się po każdym restarcie w całości od nowa
        i kolejka do telefonu puchła od duplikatów.
        """
        now = time.monotonic()

        if applied.get("steps", 0) > 0:
            if self.session_started_at is None:
                self.session_started_at = datetime.now()
                self.session_peak = {}
            self.session_last_move = now
            for field, delta in applied.items():
                self.session_peak[field] = self.session_peak.get(field, 0) + delta
        elif self.session_started_at is not None and now - self.session_last_move > SESSION_IDLE_GAP:
            self.close_session()

    def close_session(self):
        if self.session_started_at is None:
            return
        peak = self.session_peak
        started = self.session_started_at
        self.session_started_at = None
        self.session_peak = {}
        if peak.get("steps", 0) <= 0:
            return  # taśma kręciła się bez nikogo — nie ma czego zapisywać
        record = {
            "id": started.strftime("%Y%m%dT%H%M%S"),
            "start": started.isoformat(timespec="seconds"),
            "end": datetime.now().isoformat(timespec="seconds"),
            "steps": int(peak.get("steps", 0)),
            "distance_m": int(peak.get("distance_m", 0)),
            "kcal": int(peak.get("kcal", 0)),
            "elapsed_s": int(peak.get("elapsed_s", 0)),
            "sent": False,
        }
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            with SESSIONS_PATH.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            error(f"nie mogę zapisać sesji: {exc}")
        emit({"t": "session", **record})

    def publish_targets(self):
        """Cele osobno od odczytów: gdy taśma stoi, bieżnia raportuje zera,
        a panel ma pokazywać to, co zostanie zadane po starcie."""
        emit({"t": "targets", "target_speed": self.target_speed,
              "target_incline": self.target_incline})

    def phase(self, name: str, text: str):
        """Postęp startu dla panelu. Bieżnia rusza z opóźnieniem, potwierdza
        komendy po kilku sekundach i cele przyjmuje dopiero po rozpędzeniu —
        bez tego przycisk Start wygląda, jakby nic nie zrobił."""
        emit({"t": "phase", "phase": name, "text": text})

    # ---- odbiór

    def steps_from(self, sample: dict) -> float | None:
        if "steps" in sample:
            return sample["steps"]
        if "distance_m" in sample and self.stride_m > 0:
            return sample["distance_m"] / self.stride_m
        return None

    def on_treadmill_data(self, _sender, data: bytearray):
        sample = parse_treadmill_data(bytes(data))
        if not sample:
            return
        steps = self.steps_from(sample)
        if steps is not None:
            sample["steps"] = steps
        applied = self.day.update(sample) or {}
        self.latest = sample
        self.track_session(applied)
        payload = {"t": "data"}
        payload.update({k: round(v, 2) if isinstance(v, float) else v
                        for k, v in sample.items() if v is not None})
        payload.update(self.day.snapshot())
        emit(payload)

    def on_control_reply(self, _sender, data: bytearray):
        raw = bytes(data)
        if len(raw) >= 3 and raw[0] == RESPONSE_CODE:
            self.control_replies.put_nowait((raw[1], raw[2]))
        else:
            emit({"t": "control", "raw": raw.hex(" ")})

    def on_machine_status(self, _sender, data: bytearray):
        """Stan maszyny (FTMS 4.17): 0x02 to zatrzymanie przez użytkownika,
        gdzie parametr 0x01 znaczy stop, a 0x02 pauzę — bieżnia sama pauzuje,
        gdy nikt na niej nie stoi. 0x04 to start albo wznowienie."""
        raw = bytes(data)
        emit({"t": "machine", "raw": raw.hex(" ")})
        if raw[:1] == b"\x02":
            paused = len(raw) > 1 and raw[1] == 0x02
            self.belt_state = "paused" if paused else "stopped"
            emit({"t": "belt", "state": self.belt_state})
            self.phase("paused" if paused else "stopped",
                       "spauzowana — zszedłeś z taśmy" if paused else "zatrzymana")
            self.day.save()
        elif raw[:1] == b"\x03":  # wyłącznik bezpieczeństwa
            self.belt_state = "stopped"
            emit({"t": "belt", "state": self.belt_state})
            self.day.save()
        elif raw[:1] == b"\x04":
            self.belt_state = "running"
            emit({"t": "belt", "state": self.belt_state})

    # ---- wysyłka

    # Bieżnia potwierdza start nawet po 7 s (sprawdzone w logu), więc krótszy
    # limit robił z udanej komendy błąd.
    async def send_command(self, opcode: int, payload: bytes = b"", timeout: float = 10.0) -> bool:
        if not self.client or not self.client.is_connected:
            error("bieżnia nie jest połączona")
            return False
        while not self.control_replies.empty():
            self.control_replies.get_nowait()
        try:
            await self.client.write_gatt_char(CONTROL_POINT, bytes([opcode]) + payload, response=True)
        except BleakError as exc:
            error(f"zapis komendy 0x{opcode:02x} nieudany: {exc}")
            return False
        try:
            replied_op, result = await asyncio.wait_for(self.control_replies.get(), timeout)
        except asyncio.TimeoutError:
            error(f"brak odpowiedzi na komendę 0x{opcode:02x}")
            return False
        if replied_op != opcode:
            error(f"odpowiedź na inną komendę: 0x{replied_op:02x}")
            return False
        if result != RESULT_SUCCESS:
            error(f"komenda 0x{opcode:02x} odrzucona: {RESULT_NAMES.get(result, hex(result))}")
            return False
        return True

    def targets_reached(self) -> bool:
        speed_ok = (self.target_speed is None
                    or abs(self.latest.get("speed", 0) - self.target_speed) < 0.05)
        incline_ok = (self.target_incline is None
                      or abs(self.latest.get("incline", 0) - self.target_incline) < 0.05)
        return speed_ok and incline_ok

    async def apply_targets(self):
        """Dosyła prędkość i nachylenie po starcie, aż bieżnia je pokaże."""
        self.phase("spinup", "taśma rusza, czekam aż się rozpędzi")
        for attempt in range(5):
            await asyncio.sleep(6.0)
            if not self.client or not self.client.is_connected:
                self.phase("error", "rozłączyło bieżnię")
                return
            # Taśma stanęła (bieżnia zatrzymuje się sama, gdy nikt na niej nie
            # stoi) — dosyłanie celów do stojącej maszyny zwraca same błędy.
            if self.latest.get("speed", 0) <= 0:
                self.phase("failed", "taśma nie ruszyła")
                return
            if self.targets_reached():
                self.phase("running", self.running_text())
                return
            if self.target_speed is not None and abs(self.latest.get("speed", 0) - self.target_speed) >= 0.05:
                self.phase("setting", f"zadaję {self.target_speed:.1f} km/h".replace(".", ","))
                await self.send_command(OP_SET_SPEED,
                                        round(self.target_speed * 100).to_bytes(2, "little"))
            if self.target_incline is not None and abs(self.latest.get("incline", 0) - self.target_incline) >= 0.05:
                self.phase("setting", f"zadaję nachylenie {round(self.target_incline)}")
                await self.send_command(OP_SET_INCLINATION,
                                        round(self.target_incline * 10).to_bytes(2, "little", signed=True))
        self.phase("running" if self.targets_reached() else "partial", self.running_text())

    def running_text(self) -> str:
        speed = f"{self.latest.get('speed', 0):.1f}".replace(".", ",")
        return f"jedzie {speed} km/h, nachylenie {round(self.latest.get('incline', 0))}"

    async def request_control(self) -> bool:
        if self.has_control:
            return True
        self.has_control = await self.send_command(OP_REQUEST_CONTROL)
        return self.has_control

    async def handle_line(self, line: str):
        parts = line.strip().split()
        if not parts:
            return
        cmd, args = parts[0].lower(), parts[1:]

        if cmd == "ping":
            emit({"t": "pong", "connected": bool(self.client and self.client.is_connected)})
            return
        if cmd == "reset-day":
            self.day.totals = {f: 0.0 for f in DayTotals.FIELDS}
            self.day.dirty = True
            self.day.save()
            emit({"t": "data", **self.day.snapshot()})
            return

        if cmd == "start":
            self.phase("control", "przejmuję sterowanie bieżnią")
        if not await self.request_control():
            if cmd == "start":
                self.phase("error", "bieżnia nie oddała sterowania")
            return

        if cmd == "start":
            self.day.new_session()
            if args:
                self.target_speed = float(args[0])
            if len(args) > 1:
                self.target_incline = float(args[1])
            self.publish_targets()
            self.phase("starting", "wysłałem start, czekam na potwierdzenie")
            # Brak potwierdzenia nie znaczy, że taśma nie ruszyła — bywa, że
            # odpowiedź gubi się, a bieżnia startuje. Cele dosyłamy tak czy siak;
            # apply_targets i tak przerwie, gdy taśma stoi.
            if not await self.send_command(OP_START):
                self.phase("unconfirmed", "brak potwierdzenia, sprawdzam czy ruszyła")
            asyncio.create_task(self.apply_targets())
        elif cmd == "stop":
            if await self.send_command(OP_STOP, bytes([0x01])):
                self.day.save()
                self.phase("stopped", "zatrzymana")
        elif cmd == "pause":
            if await self.send_command(OP_STOP, bytes([0x02])):
                self.day.save()
                self.phase("stopped", "pauza")
        elif cmd == "speed" and args:
            kmh = max(0.0, float(args[0]))
            self.target_speed = kmh
            self.publish_targets()
            # Stojąca bieżnia nie przyjmuje ani prędkości, ani nachylenia —
            # zapamiętujemy cel i dosyłamy go po starcie.
            if self.running_belt:
                await self.send_command(OP_SET_SPEED, round(kmh * 100).to_bytes(2, "little"))
        elif cmd == "incline" and args:
            percent = float(args[0])
            self.target_incline = percent
            self.publish_targets()
            if self.running_belt:
                await self.send_command(OP_SET_INCLINATION,
                                        round(percent * 10).to_bytes(2, "little", signed=True))
        else:
            error(f"nieznana komenda: {line.strip()}")

    # ---- pętla

    async def find_device(self, patience: float = 60.0):
        """Ciągły skan zamiast pojedynczego zapytania. Bieżnia rozgłasza się tylko
        przez chwilę po włączeniu zasilania, więc trzeba nasłuchiwać bez przerwy
        i wziąć ją w momencie, gdy się odezwie. BlueZ zapomina ją po rozłączeniu,
        więc łączenie po samym adresie kończy się „device not found"."""
        status("scanning")
        found = asyncio.Event()
        hit = {}
        want = (self.address or "").upper()

        def on_detect(device, adv):
            if want:
                if device.address.upper() != want:
                    return
            else:
                uuids = [u.lower() for u in (adv.service_uuids or [])]
                if FTMS_SERVICE not in uuids:
                    return
            hit["device"] = device
            hit["name"] = adv.local_name or device.name or device.address
            found.set()

        scanner = BleakScanner(detection_callback=on_detect)
        await scanner.start()
        try:
            await asyncio.wait_for(found.wait(), patience)
        except asyncio.TimeoutError:
            pass
        finally:
            await scanner.stop()

        device = hit.get("device")
        if device is not None:
            status("found", device=hit.get("name", ""), address=device.address)
        return device

    async def session(self) -> bool:
        """Zwraca False, gdy bieżni nie ma w eterze — wtedy warto odczekać dłużej."""
        device = await self.find_device()
        if device is None:
            status("not_found")
            return False
        address = device.address
        status("connecting", address=address)
        disconnected = asyncio.Event()

        def on_disconnect(_client):
            disconnected.set()

        async with BleakClient(device, timeout=30.0, disconnected_callback=on_disconnect) as client:
            self.client = client
            self.has_control = False
            self.day.new_session()
            status("connected", address=address)

            await client.start_notify(TREADMILL_DATA, self.on_treadmill_data)
            await client.start_notify(CONTROL_POINT, self.on_control_reply)
            try:
                await client.start_notify(MACHINE_STATUS, self.on_machine_status)
            except BleakError:
                pass  # nie każda bieżnia ma status maszyny
            if self.steps_uuid:
                try:
                    await client.start_notify(self.steps_uuid, self.on_steps_char)
                except BleakError as exc:
                    error(f"nie mogę subskrybować kroków ({self.steps_uuid}): {exc}")

            await disconnected.wait()

        self.client = None
        self.close_session()
        self.day.save()
        status("disconnected")
        return True

    def on_steps_char(self, _sender, data: bytearray):
        """Kroki z własnej charakterystyki producenta — układ ustala probe.py."""
        emit({"t": "steps_raw", "raw": bytes(data).hex(" ")})

    async def connection_loop(self):
        attempt = 0
        while True:
            found = False
            try:
                found = await self.session()
                if found:
                    attempt = 0
            except (BleakError, asyncio.TimeoutError, OSError) as exc:
                error(f"połączenie nieudane: {exc}")
            if not found:
                attempt += 1
            # Bieżnia wyłączona to stan normalny, nie awaria: po kilku pustych
            # próbach schodzimy do jednego skanu na minutę, żeby nie zajmować
            # Bluetootha innym urządzeniom.
            if attempt == 0:
                delay = 5.0
            elif attempt < 5:
                delay = 10.0
            else:
                delay = 60.0
            await asyncio.sleep(delay)

    async def stdin_loop(self):
        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        while True:
            line = await reader.readline()
            if not line:
                return  # stdin zamknięty — shell zniknął
            try:
                await self.handle_line(line.decode("utf-8", "replace"))
            except Exception as exc:
                error(f"komenda nieudana: {exc}")

    async def save_loop(self):
        while True:
            await asyncio.sleep(30)
            self.day.roll_over_if_needed()
            self.day.save()

    async def run(self):
        emit({"t": "data", **self.day.snapshot()})
        emit({"t": "history", "days": read_history()})
        self.publish_targets()
        stdin_task = asyncio.create_task(self.stdin_loop())
        conn_task = asyncio.create_task(self.connection_loop())
        save_task = asyncio.create_task(self.save_loop())
        server_task = asyncio.create_task(self.server.serve()) if self.server else None
        # Czekamy tylko na zadania, których koniec naprawdę znaczy koniec pracy:
        # zamknięty stdin (zniknął shell) albo przerwana pętla połączeń.
        # Serwer dla telefonu żyje obok i jego kłopoty nie mogą ubić mostu.
        done, pending = await asyncio.wait([stdin_task, conn_task],
                                           return_when=asyncio.FIRST_COMPLETED)
        if server_task:
            server_task.cancel()
        save_task.cancel()
        for task in pending:
            task.cancel()
        self.day.save()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", help="adres bieżni; bez tego skanuje po FTMS")
    parser.add_argument("--steps-uuid", help="charakterystyka z krokami, jeśli inna niż FTMS")
    parser.add_argument("--stride", type=float, default=0.0,
                        help="długość kroku w metrach — kroki z dystansu, gdy bieżnia ich nie podaje")
    parser.add_argument("--serve", metavar="HOST:PORT",
                        help="wystaw sesje dla telefonu, np. 100.90.167.96:8787")
    parser.add_argument("--speed", type=float, default=None, help="prędkość zadawana po starcie")
    parser.add_argument("--incline", type=float, default=None, help="nachylenie zadawane po starcie")
    args = parser.parse_args()
    bridge = Bridge(args.address, args.steps_uuid, args.stride)
    bridge.target_speed = args.speed
    bridge.target_incline = args.incline
    if args.serve:
        host, _, port = args.serve.rpartition(":")
        bridge.server = PhoneServer(host or tailscale_ip(), int(port))
    await bridge.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
