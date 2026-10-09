"""A service host with a fake bridge on a private D-Bus bus, for the widget tests.

Prints one JSON line, {"address": ..., "commands": ...}: the bus address and
the file the fake bridge logs every command it receives to. Then reads lines
from stdin and hands each to the bridge as if it came from the bridge's own
input ("walk", "rest", "beat 102" are the fake bridge's test commands).
Exits when stdin closes.
"""
import asyncio
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def main():
    tests = load("spacewalk_tests", ROOT / "test_spacewalk.py")
    service = tests.service
    with tempfile.TemporaryDirectory() as folder:
        folder = Path(folder)
        (folder / "bus.conf").write_text(tests.BUS_CONFIG.format(dir=folder))
        daemon = await asyncio.create_subprocess_exec(
            "dbus-daemon", "--config-file", str(folder / "bus.conf"), "--nofork",
            "--print-address=1", stdout=asyncio.subprocess.PIPE)
        address = (await daemon.stdout.readline()).decode().strip()
        service.STATE = folder
        service.BRIDGE = folder / "fake-bridge.py"
        service.BRIDGE.write_text(tests.FAKE_BRIDGE)
        host = service.Host()
        bus = await service.load_dbus().serve(host, address)
        await host.configure([])
        print(json.dumps({"address": address, "commands": str(folder / "commands.log")}), flush=True)

        loop = asyncio.get_running_loop()
        reader = asyncio.StreamReader()
        await loop.connect_read_pipe(lambda: asyncio.StreamReaderProtocol(reader), sys.stdin)
        try:
            while line := await reader.readline():
                await host.send(line.strip())
        finally:
            host.stopping = True
            await host.stop_bridge()
            if host.supervisor:
                host.supervisor.cancel()
                await asyncio.gather(host.supervisor, return_exceptions=True)
            bus.disconnect()
            daemon.terminate()
            await daemon.wait()


asyncio.run(main())
