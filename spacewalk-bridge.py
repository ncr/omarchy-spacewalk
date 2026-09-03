#!/usr/bin/env python3
"""Bridge between the treadmill (Bluetooth, FTMS) and the Omarchy plugin.

Emits one JSON object per line on stdout:

    {"t":"status","state":"connected","device":"..."}
    {"t":"data","speed":2.5,"incline":3.0,"distance_m":1840,"kcal":62,
     "elapsed_s":1620,"steps":2705,"day_steps":7412,...}
    {"t":"error","msg":"..."}

Reads one command per line from stdin:

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

try:
    from bleak import BleakClient, BleakScanner
    from bleak.exc import BleakError
except ImportError:
    # Without bleak there is nothing to talk Bluetooth with. This error
    # lands in the panel, so it says outright what to install.
    print(json.dumps({"t": "error",
                      "msg": "python-bleak is not installed — sudo pacman -S python-bleak"}),
          flush=True)
    sys.exit(66)

FTMS_SERVICE = "00001826-0000-1000-8000-00805f9b34fb"
TREADMILL_DATA = "00002acd-0000-1000-8000-00805f9b34fb"
CONTROL_POINT = "00002ad9-0000-1000-8000-00805f9b34fb"
MACHINE_STATUS = "00002ada-0000-1000-8000-00805f9b34fb"

STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", Path.home() / ".local/state")) / "omarchy-spacewalk"

# Control point opcodes (FTMS 4.16.1)
OP_REQUEST_CONTROL = 0x00
OP_RESET = 0x01
OP_SET_SPEED = 0x02
OP_SET_INCLINATION = 0x03
OP_START = 0x07
OP_STOP = 0x08
RESPONSE_CODE = 0x80
RESULT_SUCCESS = 0x01

RESULT_NAMES = {
    0x01: "accepted",
    0x02: "not supported",
    0x03: "bad parameter",
    0x04: "rejected",
    0x05: "no control",
}


LOG_PATH = STATE_DIR / "bridge.log"
SESSIONS_PATH = STATE_DIR / "sessions.jsonl"
OPEN_SESSION_PATH = STATE_DIR / "session-open.json"

# After this many seconds without movement the walk counts as finished. The
# treadmill stops itself when nobody is standing on it, so a short break to fix
# something at the desk should not split a walk into two sessions.
SESSION_IDLE_GAP = 90


def emit(obj):
    line = json.dumps(obj, separators=(",", ":"))
    sys.stdout.write(line + "\n")
    sys.stdout.flush()
    # Copy to a file: the shell consumes the bridge's stdout, so without this
    # there is no way to see what the treadmill says while the plugin runs.
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


# ------------------------------------------------------------- treadmill data

def parse_treadmill_data(data: bytes) -> dict:
    """Parses a Treadmill Data packet (0x2ACD).

    The first two bytes are flags; each field is present only when its bit
    says so, and the fields come in the order of table 4.9.1.1 of the FTMS
    spec. Bit 0 is inverted: 0 means "instantaneous speed is in the packet".
    """
    if len(data) < 2:
        return {}
    flags = int.from_bytes(data[0:2], "little")
    pos = 2
    out = {}

    def take(width, signed=False):
        nonlocal pos
        if pos + width > len(data):
            raise ValueError("packet shorter than its flags claim")
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
            out["ramp_angle"] = take(2, signed=True) / 10.0  # degrees
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
        # Bit 13 does not exist in the FTMS spec — Urevo put a step counter
        # (uint24) here. Verified on URTM024: 179 steps per 100 m of walking,
        # while the time in the same packet grew by exactly 1/s.
        if flags & 0x2000:
            out["steps"] = take(3)
    except ValueError as exc:
        error(f"{exc}: flags 0x{flags:04x}, data {data.hex(' ')}")

    return out


# --------------------------------------------------------------- daily totals

class DayTotals:
    """Daily total: the treadmill zeroes its counters on every start, so we
    add increments instead of overwriting the sum."""

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
            error(f"cannot load {self.path}: {exc}")

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
            error(f"cannot save {self.path}: {exc}")

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
        """Takes values cumulative since the session start and adds the delta.

        Distance, calories and time count only when the same reading also
        gained steps. The treadmill counts distance from belt movement but
        steps from the person — without this condition an empty, spinning belt
        credited the day with meters and calories nobody walked (150 m instead
        of 30).
        """
        self.roll_over_if_needed()

        deltas = {}
        for f in self.FIELDS:
            if f not in sample or sample[f] is None:
                continue
            value = float(sample[f])
            previous = self.session[f]
            if previous is None:
                # First reading after a start or after connecting: no telling
                # how much of this counter was already credited, so it serves
                # only as a reference point. Without this, pressing Start
                # credited the previous walk's whole counter once more.
                self.session[f] = value
                deltas[f] = 0.0
                continue
            if value < previous:
                # The treadmill zeroed the counter — count from zero.
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
        """Drops the reference point instead of zeroing it: only the first
        reading says what to count increments from."""
        self.session = {f: None for f in self.FIELDS}

    def snapshot(self) -> dict:
        return {
            "day": self.day.isoformat(),
            "day_steps": int(self.totals["steps"]),
            "day_distance_m": int(self.totals["distance_m"]),
            "day_kcal": int(self.totals["kcal"]),
            "day_elapsed_s": int(self.totals["elapsed_s"]),
        }


# -------------------------------------------------------------------- history

HISTORY_DAYS = 120


def read_history(days: int = HISTORY_DAYS) -> dict:
    """Totals for recent days, straight from the day files. The panel draws
    its grid from this, so we read the directory once at startup, not every
    time the panel opens."""
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


# ---------------------------------------------------------------- phone server

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
    """This machine's address in the tailnet. Without it there is nowhere to
    bind the server so that the phone sees it and the rest of the network does
    not."""
    try:
        out = subprocess.run(["tailscale", "ip", "-4"], capture_output=True,
                             text=True, timeout=5).stdout.strip().splitlines()
        if out:
            return out[0].strip()
    except (OSError, subprocess.SubprocessError):
        pass
    error("no Tailscale address — the server will only listen on localhost")
    return "127.0.0.1"


class PhoneServer:
    """Three endpoints for the iPhone shortcut, over Tailscale:

        GET  /pending   walks not yet sent
        POST /ack       {"ids": [...]} — mark as sent
        GET  /today     daily totals (preview)

    Listens only on the given address, by default the Tailscale one, so it
    exposes nothing to the local network or the internet.
    """

    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        # What the last /pending handed out — so the shortcut can confirm
        # receipt in one call, without assembling JSON with the ids.
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
            # iPhone Shortcuts do not turn "2026-08-31T12:47:32" into a date
            # on their own; with a space instead of the T the "Get dates from
            # input" action copes without a format being set.
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
                return "400 Bad Request", {"error": "bad JSON"}
            return "200 OK", {"marked": mark_sent([str(i) for i in ids])}
        return "404 Not Found", {"error": "no such path"}

    async def serve(self):
        # Retry instead of giving up: after a shell restart the previous bridge
        # can hold the port a moment longer, and finishing this task used to
        # kill the whole bridge (run() ends on the first completed task).
        while True:
            try:
                server = await asyncio.start_server(self.handle, self.host, self.port)
                break
            except OSError as exc:
                error(f"port {self.host}:{self.port} is taken ({exc}) — retrying in 5 s")
                await asyncio.sleep(5.0)
        # Its own type, not "status": "status" describes the treadmill link
        # and the panel takes it directly as the connection state.
        emit({"t": "server", "address": f"{self.host}:{self.port}"})
        async with server:
            await server.serve_forever()


# ----------------------------------------------------------------- connection

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
        self.targets_task: asyncio.Task | None = None
        self.session_started_at: datetime | None = None
        self.session_last_move: float = 0.0
        self.session_last_move_wall: datetime | None = None
        self.session_peak: dict = {}
        self.server: PhoneServer | None = None
        # running | paused | stopped — pause means stepping off the belt, stop
        # a command or the safety key. The treadmill tells one from the other
        # in the machine status; the panel shows it and offers to resume.
        self.belt_state = "stopped"

    @property
    def running_belt(self) -> bool:
        return self.latest.get("speed", 0) > 0

    # ---- sessions (walks) to be sent to the phone

    def track_session(self, applied: dict):
        """Opens a walk on the first movement and closes it after
        SESSION_IDLE_GAP seconds without any.

        Sums the same increments that feed the daily counter — not the
        treadmill's readings. The readings survive a bridge restart, so a walk
        counted from them was recorded whole all over again after every
        restart, and the queue for the phone swelled with duplicates.
        """
        now = time.monotonic()

        if applied.get("steps", 0) > 0:
            if self.session_started_at is None:
                self.session_started_at = datetime.now()
                self.session_peak = {}
            self.session_last_move = now
            self.session_last_move_wall = datetime.now()
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
        try:
            OPEN_SESSION_PATH.unlink()
        except OSError:
            pass
        if peak.get("steps", 0) <= 0:
            return  # the belt spun with nobody on it — nothing worth recording
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
        self.append_session(record)

    def append_session(self, record: dict):
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            with SESSIONS_PATH.open("a") as fh:
                fh.write(json.dumps(record) + "\n")
        except OSError as exc:
            error(f"cannot save the session: {exc}")
        emit({"t": "session", **record})

    def persist_open_session(self):
        """Mirrors the walk in progress to disk. The shell kills the bridge on
        every plugin reload, and a walk held only in memory died with it: the
        steps stayed on the bar (the daily counter is saved every 30 s) but
        never reached the phone."""
        if self.session_started_at is None:
            return
        payload = {
            "start": self.session_started_at.isoformat(timespec="seconds"),
            "last_move": (self.session_last_move_wall or datetime.now()).isoformat(timespec="seconds"),
            "peak": self.session_peak,
        }
        try:
            STATE_DIR.mkdir(parents=True, exist_ok=True)
            tmp = OPEN_SESSION_PATH.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(payload))
            tmp.replace(OPEN_SESSION_PATH)
        except OSError as exc:
            error(f"cannot save the open session: {exc}")

    def recover_open_session(self):
        """A leftover open-session file means the previous bridge died
        mid-walk. Close that walk as of its last recorded movement and queue
        it for the phone."""
        try:
            raw = json.loads(OPEN_SESSION_PATH.read_text())
        except FileNotFoundError:
            return
        except (ValueError, OSError) as exc:
            error(f"cannot read {OPEN_SESSION_PATH}: {exc}")
            return
        try:
            OPEN_SESSION_PATH.unlink()
        except OSError:
            pass
        peak = raw.get("peak") or {}
        start = raw.get("start") or ""
        if peak.get("steps", 0) <= 0 or not start:
            return
        self.append_session({
            "id": start.replace("-", "").replace(":", ""),
            "start": start,
            "end": raw.get("last_move") or start,
            "steps": int(peak.get("steps", 0)),
            "distance_m": int(peak.get("distance_m", 0)),
            "kcal": int(peak.get("kcal", 0)),
            "elapsed_s": int(peak.get("elapsed_s", 0)),
            "sent": False,
        })

    def publish_targets(self):
        """Targets kept apart from readings: when the belt stands still the
        treadmill reports zeros, and the panel should show what will be set
        after start."""
        emit({"t": "targets", "target_speed": self.target_speed,
              "target_incline": self.target_incline})

    def phase(self, name: str, text: str):
        """Start progress for the panel. The treadmill starts with a delay,
        confirms commands seconds later and accepts targets only once up to
        speed — without this the Start button looks like it did nothing."""
        emit({"t": "phase", "phase": name, "text": text})

    # ---- receiving

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
        """Machine status (FTMS 4.17): 0x02 is a stop by the user, where
        parameter 0x01 means stop and 0x02 pause — the treadmill pauses on its
        own when nobody is standing on it. 0x04 is a start or a resume."""
        raw = bytes(data)
        emit({"t": "machine", "raw": raw.hex(" ")})
        if raw[:1] == b"\x02":
            paused = len(raw) > 1 and raw[1] == 0x02
            self.belt_state = "paused" if paused else "stopped"
            emit({"t": "belt", "state": self.belt_state})
            self.phase("paused" if paused else "stopped",
                       "paused — you stepped off the belt" if paused else "stopped")
            self.day.save()
        elif raw[:1] == b"\x03":  # safety key
            self.belt_state = "stopped"
            emit({"t": "belt", "state": self.belt_state})
            self.day.save()
        elif raw[:1] == b"\x04":
            resumed = self.belt_state == "paused"
            self.belt_state = "running"
            emit({"t": "belt", "state": self.belt_state})
            # Stepping back on the belt resumes it, but at the treadmill's own
            # speed and incline. The vendor app re-sent the targets silently;
            # without this the panel user had to set them again by hand.
            if resumed and (self.target_speed is not None or self.target_incline is not None):
                self.kick_targets(ensure_control=True)

    # ---- sending

    # The treadmill confirms a start as late as 7 s in (seen in the log), so
    # a shorter timeout turned a successful command into an error.
    async def send_command(self, opcode: int, payload: bytes = b"", timeout: float = 10.0) -> bool:
        if not self.client or not self.client.is_connected:
            error("the treadmill is not connected")
            return False
        while not self.control_replies.empty():
            self.control_replies.get_nowait()
        try:
            await self.client.write_gatt_char(CONTROL_POINT, bytes([opcode]) + payload, response=True)
        except BleakError as exc:
            error(f"writing command 0x{opcode:02x} failed: {exc}")
            return False
        try:
            replied_op, result = await asyncio.wait_for(self.control_replies.get(), timeout)
        except asyncio.TimeoutError:
            error(f"no reply to command 0x{opcode:02x}")
            return False
        if replied_op != opcode:
            error(f"reply to a different command: 0x{replied_op:02x}")
            return False
        if result != RESULT_SUCCESS:
            error(f"command 0x{opcode:02x} rejected: {RESULT_NAMES.get(result, hex(result))}")
            return False
        return True

    def targets_reached(self) -> bool:
        speed_ok = (self.target_speed is None
                    or abs(self.latest.get("speed", 0) - self.target_speed) < 0.05)
        incline_ok = (self.target_incline is None
                      or abs(self.latest.get("incline", 0) - self.target_incline) < 0.05)
        return speed_ok and incline_ok

    async def apply_targets(self):
        """Keeps sending speed and incline after start until the treadmill
        shows them.

        The rhythm was tuned on the hardware: the first attempt only after
        9 s, because a command sent earlier vanishes without a reply — the
        treadmill spins up to 1 km/h and only then listens. Then every 3 s,
        with a short wait for the confirmation: no reply means "ignored", so
        there is no point waiting the full 10 s as at start.
        """
        self.phase("spinup", "belt is starting, waiting for it to come up to speed")
        await asyncio.sleep(6.0)
        for attempt in range(10):
            await asyncio.sleep(3.0)
            if not self.client or not self.client.is_connected:
                self.phase("error", "the treadmill disconnected")
                return
            # The belt stopped (the treadmill stops itself when nobody is on
            # it) — sending targets to a stopped machine yields only errors.
            if self.latest.get("speed", 0) <= 0:
                self.phase("failed", "the belt did not start")
                return
            if self.targets_reached():
                self.phase("running", self.running_text())
                return
            if self.target_speed is not None and abs(self.latest.get("speed", 0) - self.target_speed) >= 0.05:
                self.phase("setting", f"setting {self.target_speed:.1f} km/h")
                await self.send_command(OP_SET_SPEED,
                                        round(self.target_speed * 100).to_bytes(2, "little"),
                                        timeout=4.0)
            if self.target_incline is not None and abs(self.latest.get("incline", 0) - self.target_incline) >= 0.05:
                self.phase("setting", f"setting incline {round(self.target_incline)}")
                await self.send_command(OP_SET_INCLINATION,
                                        round(self.target_incline * 10).to_bytes(2, "little", signed=True),
                                        timeout=4.0)
        self.phase("running" if self.targets_reached() else "partial", self.running_text())

    def running_text(self) -> str:
        speed = f"{self.latest.get('speed', 0):.1f}"
        return f"running {speed} km/h, incline {round(self.latest.get('incline', 0))}"

    def kick_targets(self, ensure_control: bool = False):
        """At most one target loop at a time: a Start from the panel and the
        0x04 status it triggers would otherwise race each other with duplicate
        commands."""
        if self.targets_task and not self.targets_task.done():
            return
        coro = self.resume_targets() if ensure_control else self.apply_targets()
        self.targets_task = asyncio.create_task(coro)

    async def resume_targets(self):
        # Control does not survive a reconnect, and a resume can be the first
        # command-worthy moment of a connection.
        if not await self.request_control():
            return
        await self.apply_targets()

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
            self.phase("control", "taking control of the treadmill")
        if not await self.request_control():
            if cmd == "start":
                self.phase("error", "the treadmill would not hand over control")
            return

        if cmd == "start":
            self.day.new_session()
            if args:
                self.target_speed = float(args[0])
            if len(args) > 1:
                self.target_incline = float(args[1])
            self.publish_targets()
            self.phase("starting", "sent start, waiting for the reply")
            # No confirmation does not mean the belt did not start — sometimes
            # the reply gets lost while the treadmill starts anyway. Targets go
            # out either way; apply_targets bails out when the belt stands.
            if not await self.send_command(OP_START):
                self.phase("unconfirmed", "no reply, checking whether the belt moved")
            self.kick_targets()
        elif cmd == "stop":
            if await self.send_command(OP_STOP, bytes([0x01])):
                self.day.save()
                self.phase("stopped", "stopped")
        elif cmd == "pause":
            if await self.send_command(OP_STOP, bytes([0x02])):
                self.day.save()
                self.phase("stopped", "paused")
        elif cmd == "speed" and args:
            kmh = max(0.0, float(args[0]))
            self.target_speed = kmh
            self.publish_targets()
            # A stopped treadmill accepts neither speed nor incline — remember
            # the target and send it after start.
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
            error(f"unknown command: {line.strip()}")

    # ---- loop

    async def find_device(self, patience: float = 60.0):
        """A continuous scan instead of a one-shot query. The treadmill
        advertises only for a moment after power-on, so we listen non-stop and
        grab it the moment it speaks up. BlueZ forgets it after a disconnect,
        so connecting by the address alone ends in "device not found"."""
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
        """Returns False when the treadmill is not on the air — then a longer
        wait is worthwhile."""
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
                pass  # not every treadmill has machine status
            if self.steps_uuid:
                try:
                    await client.start_notify(self.steps_uuid, self.on_steps_char)
                except BleakError as exc:
                    error(f"cannot subscribe to steps ({self.steps_uuid}): {exc}")

            await disconnected.wait()

        self.client = None
        self.close_session()
        self.day.save()
        status("disconnected")
        return True

    def on_steps_char(self, _sender, data: bytearray):
        """Steps from a vendor characteristic — probe.py works out the layout."""
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
                error(f"connection failed: {exc}")
            if not found:
                attempt += 1
            # A powered-off treadmill is the normal state, not a failure: after
            # a few empty tries we drop to one scan a minute, so Bluetooth is
            # not hogged from other devices.
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
                return  # stdin closed — the shell is gone
            try:
                await self.handle_line(line.decode("utf-8", "replace"))
            except Exception as exc:
                error(f"command failed: {exc}")

    async def save_loop(self):
        while True:
            await asyncio.sleep(30)
            self.day.roll_over_if_needed()
            self.day.save()
            self.persist_open_session()

    async def run(self):
        self.recover_open_session()
        emit({"t": "data", **self.day.snapshot()})
        emit({"t": "history", "days": read_history()})
        self.publish_targets()
        stdin_task = asyncio.create_task(self.stdin_loop())
        conn_task = asyncio.create_task(self.connection_loop())
        save_task = asyncio.create_task(self.save_loop())
        server_task = asyncio.create_task(self.server.serve()) if self.server else None
        # Wait only for the tasks whose end truly means the work is done:
        # a closed stdin (the shell is gone) or a broken connection loop.
        # The phone server lives alongside; its troubles must not kill the bridge.
        done, pending = await asyncio.wait([stdin_task, conn_task],
                                           return_when=asyncio.FIRST_COMPLETED)
        if server_task:
            server_task.cancel()
        save_task.cancel()
        for task in pending:
            task.cancel()
        self.close_session()
        self.day.save()


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", help="treadmill address; scans for FTMS without it")
    parser.add_argument("--steps-uuid", help="characteristic carrying steps, if different from FTMS")
    parser.add_argument("--stride", type=float, default=0.0,
                        help="stride length in meters — derives steps from distance when the treadmill reports none")
    parser.add_argument("--serve", metavar="HOST:PORT",
                        help="expose sessions for the phone, e.g. :8787 (bare port = the Tailscale address)")
    parser.add_argument("--speed", type=float, default=None, help="speed to set after start")
    parser.add_argument("--incline", type=float, default=None, help="incline to set after start")
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
