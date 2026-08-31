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
import sys
import time
from datetime import date, datetime
from pathlib import Path

from bleak import BleakClient, BleakScanner
from bleak.exc import BleakError

FTMS_SERVICE = "00001826-0000-1000-8000-00805f9b34fb"
TREADMILL_DATA = "00002acd-0000-1000-8000-00805f9b34fb"
CONTROL_POINT = "00002ad9-0000-1000-8000-00805f9b34fb"
MACHINE_STATUS = "00002ada-0000-1000-8000-00805f9b34fb"

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "omarchy-treadmill"

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
        self.session = {f: 0.0 for f in self.FIELDS}
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
        self.session = {f: 0.0 for f in self.FIELDS}
        self.load()

    def update(self, sample: dict):
        """Przyjmuje wartości narastające od początku sesji i dolicza różnicę."""
        self.roll_over_if_needed()
        for f in self.FIELDS:
            if f not in sample or sample[f] is None:
                continue
            value = float(sample[f])
            previous = self.session[f]
            if value < previous:
                # Bieżnia wyzerowała licznik — nowa sesja zaczyna się od zera.
                previous = 0.0
            delta = value - previous
            self.session[f] = value
            if delta > 0:
                self.totals[f] += delta
                self.dirty = True

    def new_session(self):
        self.session = {f: 0.0 for f in self.FIELDS}

    def snapshot(self) -> dict:
        return {
            "day": self.day.isoformat(),
            "day_steps": int(self.totals["steps"]),
            "day_distance_m": int(self.totals["distance_m"]),
            "day_kcal": int(self.totals["kcal"]),
            "day_elapsed_s": int(self.totals["elapsed_s"]),
        }


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
        self.day.update(sample)
        self.latest = sample
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
        raw = bytes(data)
        emit({"t": "machine", "raw": raw.hex(" ")})
        if raw and raw[0] in (0x02, 0x03, 0x04):  # stop, pauza, zatrzymanie awaryjne
            self.day.save()

    # ---- wysyłka

    async def send_command(self, opcode: int, payload: bytes = b"", timeout: float = 5.0) -> bool:
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

    async def apply_targets(self):
        """Dosyła prędkość i nachylenie po starcie, aż bieżnia je pokaże."""
        for _ in range(4):
            await asyncio.sleep(8.0)
            if not self.client or not self.client.is_connected:
                return
            # Taśma stanęła (bieżnia zatrzymuje się sama, gdy nikt na niej nie
            # stoi) — dosyłanie celów do stojącej maszyny zwraca same błędy.
            if self.latest.get("speed", 0) <= 0:
                return
            speed_ok = (self.target_speed is None
                        or abs(self.latest.get("speed", 0) - self.target_speed) < 0.05)
            incline_ok = (self.target_incline is None
                          or abs(self.latest.get("incline", 0) - self.target_incline) < 0.05)
            if speed_ok and incline_ok:
                return
            if not speed_ok:
                await self.send_command(OP_SET_SPEED,
                                        round(self.target_speed * 100).to_bytes(2, "little"))
            if not incline_ok:
                await self.send_command(OP_SET_INCLINATION,
                                        round(self.target_incline * 10).to_bytes(2, "little", signed=True))

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

        if not await self.request_control():
            return

        if cmd == "start":
            self.day.new_session()
            if not await self.send_command(OP_START):
                return
            # Bieżnia rozpędza się do 1 km/h i dopiero wtedy przyjmuje cele —
            # komenda wysłana od razu po starcie przepada bez odpowiedzi.
            if args:
                self.target_speed = float(args[0])
            if len(args) > 1:
                self.target_incline = float(args[1])
            asyncio.create_task(self.apply_targets())
        elif cmd == "stop":
            if await self.send_command(OP_STOP, bytes([0x01])):
                self.day.save()
        elif cmd == "pause":
            if await self.send_command(OP_STOP, bytes([0x02])):
                self.day.save()
        elif cmd == "speed" and args:
            kmh = max(0.0, float(args[0]))
            self.target_speed = kmh
            await self.send_command(OP_SET_SPEED, round(kmh * 100).to_bytes(2, "little"))
        elif cmd == "incline" and args:
            percent = float(args[0])
            self.target_incline = percent
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
        stdin_task = asyncio.create_task(self.stdin_loop())
        conn_task = asyncio.create_task(self.connection_loop())
        save_task = asyncio.create_task(self.save_loop())
        done, pending = await asyncio.wait(
            [stdin_task, conn_task, save_task], return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        self.day.save()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", help="adres bieżni; bez tego skanuje po FTMS")
    parser.add_argument("--steps-uuid", help="charakterystyka z krokami, jeśli inna niż FTMS")
    parser.add_argument("--stride", type=float, default=0.0,
                        help="długość kroku w metrach — kroki z dystansu, gdy bieżnia ich nie podaje")
    args = parser.parse_args()
    bridge = Bridge(args.address, args.steps_uuid, args.stride)
    await bridge.run()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
