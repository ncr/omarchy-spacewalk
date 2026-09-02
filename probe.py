#!/usr/bin/env python3
"""Treadmill reconnaissance over Bluetooth.

With no arguments: scans and lists candidates (name, address, advertised services).
With --address: connects, lists every service and characteristic, subscribes to
each one that can send notifications, and logs raw bytes with a timestamp.

    ./probe.py                       # find the treadmill
    ./probe.py --address XX:XX:...   # eavesdrop on everything for 120 s
"""

import argparse
import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

FTMS_SERVICE = "00001826-0000-1000-8000-00805f9b34fb"
TREADMILL_DATA = "00002acd-0000-1000-8000-00805f9b34fb"
CONTROL_POINT = "00002ad9-0000-1000-8000-00805f9b34fb"


def log(*parts):
    print(*parts, flush=True)


async def scan(seconds: float):
    log(f"Scanning for {seconds:.0f} s...")
    devices = await BleakScanner.discover(timeout=seconds, return_adv=True)
    rows = []
    for address, (device, adv) in devices.items():
        name = adv.local_name or device.name or "(no name)"
        uuids = adv.service_uuids or []
        ftms = FTMS_SERVICE in [u.lower() for u in uuids]
        rows.append((ftms, name, address, uuids, adv.rssi, adv.manufacturer_data))
    rows.sort(key=lambda r: (not r[0], -r[4]))
    log("")
    for ftms, name, address, uuids, rssi, mfr in rows:
        mark = "  <-- FTMS" if ftms else ""
        log(f"{address}  {rssi:4d} dBm  {name}{mark}")
        if uuids:
            log(f"    services: {', '.join(uuids)}")
        for company, payload in (mfr or {}).items():
            log(f"    manufacturer 0x{company:04x}: {bytes(payload).hex(' ')}")
    if not any(r[0] for r in rows):
        log("")
        log("No device advertises FTMS (0x1826). Is the treadmill powered on?")
        log("The Urevo app on the phone must be closed — the treadmill accepts a single connection.")


def describe(value: bytes) -> str:
    hex_part = value.hex(" ")
    ints = []
    for width, signed in ((2, False), (2, True)):
        for offset in range(0, len(value) - width + 1):
            ints.append(int.from_bytes(value[offset:offset + width], "little", signed=signed))
    return f"{hex_part}   (len {len(value)})"


async def wait_for_device(address: str, patience: float):
    """The treadmill advertises only briefly after waking, so we scan non-stop
    and grab it the moment it speaks up."""
    found = asyncio.Event()
    hit = {}

    def on_detect(device, adv):
        if device.address.upper() != address.upper():
            return
        hit["device"] = device
        found.set()

    scanner = BleakScanner(detection_callback=on_detect)
    await scanner.start()
    try:
        await asyncio.wait_for(found.wait(), patience)
    except asyncio.TimeoutError:
        pass
    finally:
        await scanner.stop()
    return hit.get("device")


async def control(client, opcode: int, payload: bytes = b""):
    """One command to the control point; the reply shows up in the notify log."""
    await client.write_gatt_char(CONTROL_POINT, bytes([opcode]) + payload, response=True)
    await asyncio.sleep(1.5)


async def probe(address: str, seconds: float, do_start: bool = False,
                speed: float = 2.5, incline: float = 3.0):
    start = time.monotonic()
    counts: dict[str, int] = {}
    last: dict[str, bytes] = {}

    def on_notify(char):
        def handler(_sender, data: bytearray):
            key = char.uuid
            counts[key] = counts.get(key, 0) + 1
            value = bytes(data)
            if last.get(key) == value:
                return  # unchanged — don't clutter the log
            last[key] = value
            elapsed = time.monotonic() - start
            log(f"[{elapsed:7.2f}s] {key}  {describe(value)}")
        return handler

    log(f"Waiting for {address} — press a button on the treadmill console to wake it.")
    device = await wait_for_device(address, 180.0)
    if device is None:
        log("No sign of it for three minutes.")
        return
    log("Found it. Connecting...")
    async with BleakClient(device, timeout=30.0) as client:
        log("Connected.\n")
        log("=== SERVICES AND CHARACTERISTICS ===")
        notifiable = []
        for service in client.services:
            log(f"\nservice {service.uuid}  {service.description}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                log(f"  char {char.uuid}  [{props}]  {char.description}")
                if "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char)
                        log(f"       read: {bytes(value).hex(' ')}")
                    except Exception as exc:
                        log(f"       read failed: {exc}")
                if "notify" in char.properties or "indicate" in char.properties:
                    notifiable.append(char)

        log("\n=== NOTIFICATIONS ===")
        log(f"Subscribing to {len(notifiable)} characteristics. Step on the treadmill and walk.")
        log("Count your steps out loud — later we compare which counter grew by the same amount.\n")
        for char in notifiable:
            try:
                await client.start_notify(char, on_notify(char))
            except Exception as exc:
                log(f"  could not subscribe to {char.uuid}: {exc}")

        if do_start:
            log("\nStarting the belt...")
            await control(client, 0x00)                                        # request control
            await control(client, 0x07)                                        # start
            await control(client, 0x03, round(incline * 10).to_bytes(2, "little", signed=True))
            log("Start accepted. Step onto the belt and walk, counting your steps.\n")
            # A speed set right after start tends to be ignored — the treadmill
            # spins up to 1 km/h and only then accepts the target. Hence three
            # spaced attempts.
            for attempt in range(3):
                await asyncio.sleep(8.0)
                log(f"Setting {speed} km/h (attempt {attempt + 1})")
                await control(client, 0x02, round(speed * 100).to_bytes(2, "little"))

        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            pass

        if do_start:
            log("\nStopping the belt.")
            try:
                await control(client, 0x08, bytes([0x01]))
            except Exception as exc:
                log(f"stop failed: {exc}")

        log("\n=== SUMMARY ===")
        for uuid, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            log(f"{uuid}  {count} packets, last: {last[uuid].hex(' ')}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", help="treadmill address; scan only without it")
    parser.add_argument("--seconds", type=float, default=120.0, help="how long to listen")
    parser.add_argument("--scan-seconds", type=float, default=12.0)
    parser.add_argument("--start", action="store_true", help="start the belt and stop it at the end")
    parser.add_argument("--speed", type=float, default=2.5)
    parser.add_argument("--incline", type=float, default=3.0)
    args = parser.parse_args()

    if args.address:
        await probe(args.address, args.seconds, args.start, args.speed, args.incline)
    else:
        await scan(args.scan_seconds)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
