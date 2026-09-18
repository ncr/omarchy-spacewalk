import asyncio
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import tempfile
import time
import unittest


def module(name, filename):
    spec = importlib.util.spec_from_file_location(name, Path(__file__).with_name(filename))
    obj = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(obj)
    return obj


bridge = module("bridge", "spacewalk-bridge.py")
service = module("service", "spacewalk-service.py")
# CounterTests swaps bridge.emit for a stub; the log tests need the real one.
real_emit = bridge.emit


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


class StateDirTestCase(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.dir = Path(self.temp.name)
        for name, value in [("STATE_DIR", self.dir),
                            ("LOG_PATH", self.dir / "bridge.log"),
                            ("OPEN_SESSION_PATH", self.dir / "session-open.json"),
                            ("SESSIONS_PATH", self.dir / "sessions.jsonl"),
                            ("TARGETS_PATH", self.dir / "targets.json"),
                            ("log_bytes", None)]:
            self.addCleanup(setattr, bridge, name, getattr(bridge, name))
            setattr(bridge, name, value)


class LogCapTests(StateDirTestCase):
    def setUp(self):
        super().setUp()
        self.addCleanup(setattr, bridge, "LOG_MAX_BYTES", bridge.LOG_MAX_BYTES)
        bridge.LOG_MAX_BYTES = 100
        self.log = self.dir / "bridge.log"
        self.old = self.dir / "bridge.log.1"

    def test_rotates_at_the_cap_and_keeps_one_old_file(self):
        line = "x" * 39 + "\n"
        bridge.append_log(line)
        bridge.append_log(line)
        self.assertEqual(self.log.stat().st_size, 80)
        self.assertFalse(self.old.exists())
        bridge.append_log("second\n")  # 80 + 7 still fits
        bridge.append_log(line)        # 87 + 40 does not
        self.assertEqual(self.old.read_text(), line * 2 + "second\n")
        self.assertEqual(self.log.read_text(), line)
        bridge.append_log(line)
        bridge.append_log("third\n" * 4)
        # The second rotation replaces bridge.log.1 instead of piling up files.
        self.assertEqual(self.old.read_text(), line * 2)
        self.assertEqual(self.log.read_text(), "third\n" * 4)
        self.assertEqual(sorted(p.name for p in self.dir.iterdir()),
                         ["bridge.log", "bridge.log.1"])

    def test_counts_what_an_earlier_bridge_left(self):
        self.log.write_text("o" * 5000)
        bridge.append_log("new\n")
        self.assertEqual(self.old.read_text(), "o" * 5000)
        self.assertEqual(self.log.read_text(), "new\n")

    def test_one_oversized_line_does_not_rotate_an_empty_log(self):
        bridge.append_log("y" * 500 + "\n")
        self.assertFalse(self.old.exists())
        self.assertEqual(self.log.stat().st_size, 501)

    def test_does_not_stat_on_every_line(self):
        bridge.append_log("first\n")
        old_lstat = bridge.os.lstat
        self.addCleanup(setattr, bridge.os, "lstat", old_lstat)
        def no_stat(*args, **kwargs):
            raise AssertionError("stat on a later line")
        bridge.os.lstat = no_stat
        bridge.append_log("later\n")
        self.assertEqual(self.log.read_text(), "first\nlater\n")

    def test_recovers_when_the_log_is_removed_under_it(self):
        bridge.append_log("z" * 90 + "\n")
        self.log.unlink()
        with self.assertRaises(OSError):
            bridge.append_log("z" * 90 + "\n")  # nothing to rotate any more
        bridge.append_log("after\n")
        self.assertEqual(self.log.read_text(), "after\n")

    def test_emit_survives_a_failing_log(self):
        def full_disk(text):
            raise OSError("no space left on device")
        self.addCleanup(setattr, bridge, "append_log", bridge.append_log)
        bridge.append_log = full_disk
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            real_emit({"t": "data", "steps": 1})
        self.assertEqual(json.loads(out.getvalue()), {"t": "data", "steps": 1})

    def test_emit_goes_through_the_cap(self):
        with contextlib.redirect_stdout(io.StringIO()):
            for n in range(10):
                real_emit({"t": "data", "steps": n})
        self.assertLessEqual(self.log.stat().st_size, 100)
        self.assertLessEqual(self.old.stat().st_size, 100)
        self.assertIn('"steps":9', self.log.read_text())


class StaleTempTests(StateDirTestCase):
    def make(self, name, age_s=2 * 3600, text="{}"):
        path = self.dir / name
        path.write_text(text)
        then = time.time() - age_s
        os.utime(path, (then, then), follow_symlinks=False)
        return path

    def test_removes_only_old_write_state_leftovers(self):
        stale = [self.make("targets.json.abcd1234.tmp"),
                 self.make("sessions.jsonl.k_2xq9zp.tmp"),
                 self.make("session-open.json.0a1b2c3d.tmp"),
                 self.make("2026-09-08.json.qwertyui.tmp")]
        keep = [self.make("targets.json"),
                self.make("targets.json.fresh123.tmp", age_s=60),
                self.make("2026-09-08.json"),
                self.make("sessions.jsonl"),
                self.make("sessions.jsonl.bak"),
                self.make("sessions.jsonl.bak-recovery"),
                self.make("heart-2026-09-08.jsonl"),
                self.make("recovery-2026-09-08-1242.json"),
                self.make("service-args.json"),
                self.make("bridge.lock"),
                self.make("bridge.log"),
                # Not names write_state() makes: an unknown target, no random
                # part, a date that is not one.
                self.make("notes.txt.abcd1234.tmp"),
                self.make("targets.json.tmp"),
                self.make(".tmp"),
                self.make("2026-13-40.json.abcd1234.tmp"),
                self.make("heart-2026-09-08.jsonl.abcd1234.tmp")]
        backups = self.dir / "backups"
        backups.mkdir()
        nested = backups / "targets.json.abcd1234.tmp"
        nested.write_text("{}")
        os.utime(nested, (0, 0))
        self.assertEqual(bridge.remove_stale_temp_files(), len(stale))
        for path in stale:
            self.assertFalse(path.exists(), path.name)
        for path in keep + [nested]:
            self.assertTrue(path.exists(), path.name)

    def test_leaves_symlinks_and_directories_alone(self):
        outside = tempfile.NamedTemporaryFile(delete=False)
        outside.close()
        self.addCleanup(os.unlink, outside.name)
        os.utime(outside.name, (0, 0))
        link = self.dir / "targets.json.linklink.tmp"
        link.symlink_to(outside.name)
        folder = self.dir / "targets.json.dirdirdi.tmp"
        folder.mkdir()
        os.utime(folder, (0, 0))
        self.assertEqual(bridge.remove_stale_temp_files(), 0)
        self.assertTrue(link.is_symlink())
        self.assertTrue(Path(outside.name).exists())
        self.assertTrue(folder.is_dir())

    def test_leaves_files_of_another_owner_alone(self):
        path = self.make("targets.json.abcd1234.tmp")
        old_getuid = bridge.os.getuid
        self.addCleanup(setattr, bridge.os, "getuid", old_getuid)
        bridge.os.getuid = lambda: old_getuid() + 1
        self.assertEqual(bridge.remove_stale_temp_files(), 0)
        self.assertTrue(path.exists())

    def test_missing_state_dir_is_not_an_error(self):
        bridge.STATE_DIR = self.dir / "absent"
        self.assertEqual(bridge.remove_stale_temp_files(), 0)

    def test_a_killed_write_is_cleaned_up_on_the_next_start(self):
        # What a bridge killed inside write_state() leaves: the temp file made
        # by mkstemp, never renamed.
        fd, tmp = tempfile.mkstemp(dir=str(self.dir), prefix="targets.json.", suffix=".tmp")
        os.close(fd)
        os.utime(tmp, (0, 0))
        self.assertTrue(bridge.is_state_temp_name(os.path.basename(tmp)))
        self.assertEqual(bridge.remove_stale_temp_files(), 1)
        self.assertEqual(list(self.dir.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
