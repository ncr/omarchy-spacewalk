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
