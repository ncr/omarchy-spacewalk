import asyncio
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


bridge = module("bridge", "spacewalk-bridge.py")
service = module("service", "spacewalk-service.py")


class CounterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        bridge.STATE_DIR = Path(self.temp.name)
        bridge.OPEN_SESSION_PATH = bridge.STATE_DIR / "session-open.json"
        bridge.SESSIONS_PATH = bridge.STATE_DIR / "sessions.jsonl"
        bridge.TARGETS_PATH = bridge.STATE_DIR / "targets.json"
        bridge.emit = lambda obj: None

    def test_reconnect_credits_offline_steps_once(self):
        day = bridge.DayTotals()
        day.update({"steps": 0})
        day.update({"steps": 481})
        day.save()
        for value in [525, 525, 525, 526]:
            day = bridge.DayTotals()
            day.update({"steps": value})
            day.save()
            self.assertEqual(day.totals["steps"], value)

    def test_reset_zero_is_persisted_without_new_steps(self):
        day = bridge.DayTotals()
        day.update({"steps": 0})
        day.update({"steps": 525})
        day.save()
        day.update({"steps": 0})
        day.save()
        day = bridge.DayTotals()
        self.assertEqual(day.session["steps"], 0)
        day.update({"steps": 600})
        self.assertEqual(day.totals["steps"], 1125)

    def test_each_displayed_gain_is_already_on_disk(self):
        b = bridge.Bridge(None, None, 0)
        b.adopt_targets = lambda sample: None
        values = iter([0, 481, 525, 0, 1])
        old_parse = bridge.parse_treadmill_data
        bridge.parse_treadmill_data = lambda data: {"steps": next(values)}
        self.addCleanup(setattr, bridge, "parse_treadmill_data", old_parse)
        observed = []
        def check(event):
            if event.get("t") == "data":
                saved = json.loads(b.day.path.read_text())
                self.assertEqual(saved["steps"], event["day_steps"])
                self.assertEqual(saved["session_ref"]["steps"], event["steps"])
                observed.append(event["day_steps"])
        bridge.emit = check
        for _ in range(5):
            b.on_treadmill_data(None, b"dummy")
        self.assertEqual(observed, [0, 481, 525, 525, 526])

    def test_empty_belt_does_not_add_distance(self):
        day = bridge.DayTotals()
        day.update({"steps": 0, "distance_m": 0})
        day.update({"steps": 0, "distance_m": 100})
        day.update({"steps": 1, "distance_m": 110})
        self.assertEqual(day.totals["distance_m"], 10)

    def test_failed_disk_write_does_not_publish_uncommitted_total(self):
        b = bridge.Bridge(None, None, 0)
        b.adopt_targets = lambda sample: None
        b.day.update({"steps": 0})
        old_parse, old_write = bridge.parse_treadmill_data, bridge.write_state
        bridge.parse_treadmill_data = lambda data: {"steps": 44}
        def failed_write(*args):
            raise OSError("disk unavailable")
        bridge.write_state = failed_write
        self.addCleanup(setattr, bridge, "parse_treadmill_data", old_parse)
        self.addCleanup(setattr, bridge, "write_state", old_write)
        events = []
        bridge.emit = events.append
        b.on_treadmill_data(None, b"dummy")
        self.assertFalse(any(e.get("t") == "data" for e in events))
        self.assertTrue(b.day.dirty)
        bridge.write_state = old_write
        b.on_treadmill_data(None, b"dummy")
        self.assertEqual(events[-1]["day_steps"], 44)
        self.assertEqual(json.loads(b.day.path.read_text())["steps"], 44)


class HeartPacketTests(unittest.TestCase):
    def test_magene_packet(self):
        # As received from the strap: 8-bit rate, contact sensed, RR present.
        self.assertEqual(bridge.parse_heart_rate(bytes.fromhex("16607102")),
                         {"bpm": 96, "contact": True})

    def test_wide_rate_and_no_contact_sensor(self):
        self.assertEqual(bridge.parse_heart_rate(bytes([0x01, 0x2C, 0x01])),
                         {"bpm": 300, "contact": None})

    def test_contact_lost(self):
        self.assertEqual(bridge.parse_heart_rate(bytes([0x04, 0])), {"bpm": 0, "contact": False})

    def test_truncated(self):
        self.assertEqual(bridge.parse_heart_rate(b"\x01\x60"), {})
        self.assertEqual(bridge.parse_heart_rate(b""), {})


class HeartNotesTests(unittest.TestCase):
    def run_stream(self, notes, stream, start=0.0):
        """stream: (seconds, bpm, speed, incline) stretches, fed at 2 readings/s."""
        out, now = [], start
        for seconds, bpm, speed, incline in stream:
            for _ in range(int(seconds * 2)):
                value = bpm(now) if callable(bpm) else bpm
                for note in notes.feed(now, round(value), speed, incline):
                    out.append((now, note))
                now += 0.5
        return out, now

    def kinds(self, found):
        return [note["kind"] for _, note in found]

    def test_jump_at_steady_load(self):
        found, _ = self.run_stream(bridge.HeartNotes(), [(200, 100, 2.5, 3), (30, 125, 2.5, 3)])
        self.assertEqual(self.kinds(found), ["jump"])
        at, note = found[0]
        # Reported once the new rate has held, not at its first reading.
        self.assertAlmostEqual(at, 200 + bridge.HeartNotes.JUMP_HOLD, delta=1.0)
        self.assertEqual(note["text"], "Jumped from 100 to 125 bpm within 20 s at a steady 2.5 km/h, 3%")

    def test_short_spike_is_not_a_jump(self):
        found, _ = self.run_stream(bridge.HeartNotes(),
                                   [(200, 100, 2.5, 3), (2, 190, 2.5, 3), (60, 100, 2.5, 3)])
        self.assertEqual(found, [])

    def test_dropout_is_not_a_jump(self):
        found, _ = self.run_stream(bridge.HeartNotes(),
                                   [(200, 100, 2.5, 3), (3, 45, 2.5, 3), (60, 100, 2.5, 3)])
        self.assertEqual(found, [])

    def test_rise_after_a_faster_belt_is_only_a_load_marker(self):
        found, _ = self.run_stream(bridge.HeartNotes(), [(200, 100, 2.5, 3), (60, 125, 4.0, 3)])
        self.assertEqual(self.kinds(found), ["load"])
        self.assertEqual(found[0][1]["text"], "Now 4.0 km/h, 3% (was 2.5 km/h, 3%)")

    def test_belt_ramp_gives_one_marker(self):
        ramp = [(1, 90, speed / 10, 0) for speed in range(10, 26)]
        found, _ = self.run_stream(bridge.HeartNotes(), [(30, 90, 0, 0)] + ramp + [(30, 95, 2.5, 0)])
        self.assertEqual([note["text"] for _, note in found], ["Belt started: 2.5 km/h, 0%"])

    def test_fall(self):
        found, _ = self.run_stream(bridge.HeartNotes(), [(200, 130, 2.5, 3), (30, 100, 2.5, 3)])
        self.assertEqual(self.kinds(found), ["fall"])

    def test_recovery_after_a_long_walk(self):
        found, _ = self.run_stream(bridge.HeartNotes(), [
            (400, 112, 3.0, 3),
            (70, lambda now: max(90, 112 - (now - 400) * 0.4), 0, 0)])
        self.assertEqual(self.kinds(found), ["load", "recovery"])
        self.assertEqual(found[1][1]["text"], "Recovery: 112 to 90 bpm in the minute after stopping")

    def test_no_recovery_after_a_short_walk(self):
        found, _ = self.run_stream(bridge.HeartNotes(), [(100, 112, 3.0, 3), (70, 95, 0, 0)])
        self.assertNotIn("recovery", self.kinds(found))

    def test_high_notes_once_until_the_rate_comes_down(self):
        found, _ = self.run_stream(bridge.HeartNotes(limit=150), [
            (120, lambda now: min(155, 120 + now * 0.5), 3.0, 3), (120, 155, 3.0, 3),
            (120, lambda now: max(140, 155 - (now - 240) * 0.5), 3.0, 3),
            (120, lambda now: min(155, 140 + (now - 360) * 0.5), 3.0, 3), (60, 155, 3.0, 3)])
        self.assertEqual(self.kinds(found), ["high", "high"])

    def test_limit_off(self):
        found, _ = self.run_stream(bridge.HeartNotes(), [(300, 170, 3.0, 3)])
        self.assertEqual(found, [])

    def test_drift(self):
        found, _ = self.run_stream(bridge.HeartNotes(), [
            (1500, lambda now: 100 + now / 60, 3.0, 3)])
        self.assertEqual(self.kinds(found), ["drift"])
        self.assertIn("at a steady 3.0 km/h, 3%", found[0][1]["text"])

    def test_silence_starts_the_windows_over(self):
        notes = bridge.HeartNotes()
        _, now = self.run_stream(notes, [(200, 100, 2.5, 3)])
        found, _ = self.run_stream(notes, [(200, 130, 2.5, 3)], start=now + 60)
        self.assertEqual(found, [])


class HeartDayTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        bridge.STATE_DIR = Path(self.temp.name)
        bridge.emit = lambda obj, log=True: None

    def test_restart_keeps_the_chart(self):
        import time
        now = int(time.time())
        day = bridge.HeartDay()
        for i in range(1200):
            day.add("p", [now + i * 5, 100 + i % 7, 2.5, 3], now)
        day.add("n", {"at": now + 50, "kind": "jump", "text": "x", "bpm": 120}, now)
        with day.path.open("a") as fh:
            fh.write("not json\n{\"p\":[1,2]}\n")
        again = bridge.HeartDay()
        self.assertEqual(again.points, day.points)
        self.assertEqual(again.notes, day.notes)
        messages = list(again.messages())
        self.assertTrue(messages[0]["reset"])
        self.assertEqual(len(messages[0]["notes"]), 1)
        self.assertEqual(sum((m["points"] for m in messages[1:]), []), day.points)
        # The service host reads lines with a 64 KB limit.
        self.assertLess(max(len(json.dumps(m)) for m in messages), 32768)

    def test_bridge_buckets_packets_into_points(self):
        import time
        b = bridge.Bridge(None, None, 0)
        events = []
        bridge.emit = lambda obj, log=True: events.append(obj)
        clock = [1_800_000_000.0]
        old_time = time.time
        time.time = lambda: clock[0]
        self.addCleanup(setattr, time, "time", old_time)
        for bpm in [100] * 10 + [110] * 10 + [0] * 10 + [120] * 10:
            flags = 0x16 if bpm else 0x14          # rate 0: contact lost
            b.on_heart(None, bytearray([flags, bpm, 0, 0]))
            clock[0] += 0.5
        b.flush_heart_point()
        points = [e["point"] for e in events if e["t"] == "hr_point"]
        self.assertEqual([p[1] for p in points], [100, 110, 120])
        self.assertEqual([p[0] for p in points], [1_800_000_005, 1_800_000_010, 1_800_000_020])
        self.assertEqual(bridge.HeartDay().points, points)


class FakeScanner:
    running = 0
    started = 0
    callbacks = []

    def __init__(self, detection_callback):
        self.callback = detection_callback

    async def start(self):
        if FakeScanner.running:
            raise RuntimeError("Operation already in progress")
        FakeScanner.running += 1
        FakeScanner.started += 1
        FakeScanner.callbacks.append(self.callback)

    async def stop(self):
        FakeScanner.running -= 1
        FakeScanner.callbacks.remove(self.callback)

    @classmethod
    def advertise(cls, name):
        for callback in list(cls.callbacks):
            callback(name, None)


class RadioTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        FakeScanner.running = FakeScanner.started = 0
        FakeScanner.callbacks = []
        old = bridge.BleakScanner
        bridge.BleakScanner = FakeScanner
        self.addCleanup(setattr, bridge, "BleakScanner", old)

    async def test_two_waiters_share_one_scan(self):
        radio = bridge.Radio()
        treadmill = asyncio.create_task(radio.wait_for(lambda d, a: d == "treadmill", 1))
        strap = asyncio.create_task(radio.wait_for(lambda d, a: d == "strap", 1))
        await asyncio.sleep(0.01)
        self.assertEqual(FakeScanner.started, 1)
        FakeScanner.advertise("strap")
        self.assertEqual(await strap, ("strap", None))
        self.assertEqual(FakeScanner.running, 1)      # the treadmill is still being looked for
        FakeScanner.advertise("treadmill")
        self.assertEqual(await treadmill, ("treadmill", None))
        self.assertEqual(FakeScanner.running, 0)

    async def test_listener_does_not_scan_by_itself(self):
        radio = bridge.Radio()
        strap = asyncio.create_task(radio.wait_for(lambda d, a: d == "strap", 1, drives=False))
        await asyncio.sleep(0.01)
        self.assertEqual(FakeScanner.started, 0)
        treadmill = asyncio.create_task(radio.wait_for(lambda d, a: d == "treadmill", 0.05))
        await asyncio.sleep(0.01)
        FakeScanner.advertise("strap")
        self.assertEqual(await strap, ("strap", None))
        self.assertIsNone(await treadmill)
        self.assertEqual(FakeScanner.running, 0)

    async def test_cancelled_waiter_stops_the_scan(self):
        radio = bridge.Radio()
        task = asyncio.create_task(radio.wait_for(lambda d, a: False, 30))
        await asyncio.sleep(0.01)
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        self.assertEqual(FakeScanner.running, 0)
        self.assertEqual(radio.waiters, [])


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        service.STATE = Path(self.temp.name)
        service.BRIDGE = service.STATE / "fake-bridge.py"
        service.BRIDGE.write_text('''import json, os, sys, time
print(json.dumps({"t":"status","state":"connected"}), flush=True)
print(json.dumps({"t":"data","day":"2026-09-08","day_steps":10042,"pid":os.getpid()}), flush=True)
for line in sys.stdin:
 print(json.dumps({"t":"echo","command":line.strip(),"pid":os.getpid()}), flush=True)
''')
        self.host = service.Host()
        self.sock = str(service.STATE / "test.sock")
        self.server = await asyncio.start_unix_server(self.host.serve_client, path=self.sock)

    async def asyncTearDown(self):
        self.host.stopping = True
        await self.host.stop_bridge()
        if self.host.supervisor:
            self.host.supervisor.cancel()
            await asyncio.gather(self.host.supervisor, return_exceptions=True)
        self.server.close()
        await self.server.wait_closed()

    async def connect(self):
        r, w = await asyncio.open_unix_connection(self.sock)
        w.write(b'{"args":[]}\n')
        await w.drain()
        while True:
            event = json.loads(await asyncio.wait_for(r.readline(), 2))
            if event["t"] == "data":
                return r, w, event

    async def test_twenty_panel_reloads_keep_same_bridge_and_total(self):
        pid = None
        for _ in range(20):
            r, w, event = await self.connect()
            if pid is None:
                pid = event["pid"]
            self.assertEqual(event["pid"], pid)
            self.assertEqual(event["day_steps"], 10042)
            w.write(b"ping\n")
            await w.drain()
            while True:
                reply = json.loads(await asyncio.wait_for(r.readline(), 2))
                if reply["t"] == "echo":
                    break
            self.assertEqual(reply["command"], "ping")
            w.close()
            await w.wait_closed()
        self.assertIsNone(self.host.process.returncode)

    async def test_backend_crash_restarts_without_panel(self):
        r, w, event = await self.connect()
        pid = event["pid"]
        w.close()
        await w.wait_closed()
        self.host.process.kill()
        await self.host.process.wait()
        for _ in range(70):
            await asyncio.sleep(0.1)
            if self.host.cache.get("data", {}).get("pid") != pid:
                break
        self.assertNotEqual(self.host.cache["data"]["pid"], pid)
        self.assertEqual(self.host.cache["data"]["day_steps"], 10042)


class InstallationTests(unittest.IsolatedAsyncioTestCase):
    async def test_removal_stops_service(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "manifest.json"
            manifest.write_text("{}")
            stop = asyncio.Event()
            watcher = asyncio.create_task(service.watch_installation(stop, manifest, .01, .04))
            await asyncio.sleep(.03)
            self.assertFalse(stop.is_set())
            manifest.unlink()
            await asyncio.wait_for(watcher, .3)
            self.assertTrue(stop.is_set())

    async def test_brief_update_does_not_stop_service(self):
        with tempfile.TemporaryDirectory() as folder:
            manifest = Path(folder) / "manifest.json"
            manifest.write_text("{}")
            stop = asyncio.Event()
            watcher = asyncio.create_task(service.watch_installation(stop, manifest, .01, .08))
            try:
                manifest.unlink()
                await asyncio.sleep(.03)
                manifest.write_text("{}")
                await asyncio.sleep(.1)
                self.assertFalse(stop.is_set())
            finally:
                watcher.cancel()
                await asyncio.gather(watcher, return_exceptions=True)


if __name__ == "__main__":
    unittest.main()
