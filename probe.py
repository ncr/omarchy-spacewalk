#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.11"
# dependencies = ["bleak>=0.22"]
# ///
"""Rozpoznanie bieżni po Bluetooth.

Bez argumentów: skanuje i wypisuje kandydatów (nazwa, adres, reklamowane serwisy).
Z --address: łączy się, wypisuje wszystkie serwisy i charakterystyki, subskrybuje
każdą, która umie wysyłać powiadomienia, i loguje surowe bajty ze znacznikiem czasu.

    ./probe.py                       # znajdź bieżnię
    ./probe.py --address XX:XX:...   # podsłuchaj wszystko przez 120 s
"""

import argparse
import asyncio
import sys
import time

from bleak import BleakClient, BleakScanner

FTMS_SERVICE = "00001826-0000-1000-8000-00805f9b34fb"
TREADMILL_DATA = "00002acd-0000-1000-8000-00805f9b34fb"


def log(*parts):
    print(*parts, flush=True)


async def scan(seconds: float):
    log(f"Skanuję {seconds:.0f} s...")
    devices = await BleakScanner.discover(timeout=seconds, return_adv=True)
    rows = []
    for address, (device, adv) in devices.items():
        name = adv.local_name or device.name or "(bez nazwy)"
        uuids = adv.service_uuids or []
        ftms = FTMS_SERVICE in [u.lower() for u in uuids]
        rows.append((ftms, name, address, uuids, adv.rssi))
    rows.sort(key=lambda r: (not r[0], -r[4]))
    log("")
    for ftms, name, address, uuids, rssi in rows:
        mark = "  <-- FTMS" if ftms else ""
        log(f"{address}  {rssi:4d} dBm  {name}{mark}")
        if uuids:
            log(f"    serwisy: {', '.join(uuids)}")
    if not any(r[0] for r in rows):
        log("")
        log("Żadne urządzenie nie reklamuje FTMS (0x1826). Bieżnia włączona?")
        log("Appka Urevo w telefonie musi być zamknięta — bieżnia przyjmuje jedno połączenie.")


def describe(value: bytes) -> str:
    hex_part = value.hex(" ")
    ints = []
    for width, signed in ((2, False), (2, True)):
        for offset in range(0, len(value) - width + 1):
            ints.append(int.from_bytes(value[offset:offset + width], "little", signed=signed))
    return f"{hex_part}   (len {len(value)})"


async def probe(address: str, seconds: float):
    start = time.monotonic()
    counts: dict[str, int] = {}
    last: dict[str, bytes] = {}

    def on_notify(char):
        def handler(_sender, data: bytearray):
            key = char.uuid
            counts[key] = counts.get(key, 0) + 1
            value = bytes(data)
            if last.get(key) == value:
                return  # bez zmian — nie zaśmiecaj logu
            last[key] = value
            elapsed = time.monotonic() - start
            log(f"[{elapsed:7.2f}s] {key}  {describe(value)}")
        return handler

    log(f"Łączę z {address}...")
    async with BleakClient(address, timeout=30.0) as client:
        log("Połączono.\n")
        log("=== SERWISY I CHARAKTERYSTYKI ===")
        notifiable = []
        for service in client.services:
            log(f"\nserwis {service.uuid}  {service.description}")
            for char in service.characteristics:
                props = ",".join(char.properties)
                log(f"  char {char.uuid}  [{props}]  {char.description}")
                if "read" in char.properties:
                    try:
                        value = await client.read_gatt_char(char)
                        log(f"       odczyt: {bytes(value).hex(' ')}")
                    except Exception as exc:
                        log(f"       odczyt nieudany: {exc}")
                if "notify" in char.properties or "indicate" in char.properties:
                    notifiable.append(char)

        log("\n=== POWIADOMIENIA ===")
        log(f"Subskrybuję {len(notifiable)} charakterystyk. Wejdź na bieżnię i idź.")
        log("Licz kroki na głos — potem porównamy, który licznik urósł o tyle samo.\n")
        for char in notifiable:
            try:
                await client.start_notify(char, on_notify(char))
            except Exception as exc:
                log(f"  nie udało się subskrybować {char.uuid}: {exc}")

        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            pass

        log("\n=== PODSUMOWANIE ===")
        for uuid, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            log(f"{uuid}  {count} pakietów, ostatni: {last[uuid].hex(' ')}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", help="adres bieżni; bez tego tylko skan")
    parser.add_argument("--seconds", type=float, default=120.0, help="jak długo słuchać")
    parser.add_argument("--scan-seconds", type=float, default=12.0)
    args = parser.parse_args()

    if args.address:
        await probe(args.address, args.seconds)
    else:
        await scan(args.scan_seconds)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        sys.exit(0)
