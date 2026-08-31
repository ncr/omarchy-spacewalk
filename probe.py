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
CONTROL_POINT = "00002ad9-0000-1000-8000-00805f9b34fb"


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
        rows.append((ftms, name, address, uuids, adv.rssi, adv.manufacturer_data))
    rows.sort(key=lambda r: (not r[0], -r[4]))
    log("")
    for ftms, name, address, uuids, rssi, mfr in rows:
        mark = "  <-- FTMS" if ftms else ""
        log(f"{address}  {rssi:4d} dBm  {name}{mark}")
        if uuids:
            log(f"    serwisy: {', '.join(uuids)}")
        for company, payload in (mfr or {}).items():
            log(f"    producent 0x{company:04x}: {bytes(payload).hex(' ')}")
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


async def wait_for_device(address: str, patience: float):
    """Bieżnia rozgłasza się tylko chwilę po obudzeniu, więc skanujemy bez przerwy
    i bierzemy ją w momencie, gdy się odezwie."""
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
    """Jedna komenda do punktu sterowania; odpowiedź widać w logu powiadomień."""
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
                return  # bez zmian — nie zaśmiecaj logu
            last[key] = value
            elapsed = time.monotonic() - start
            log(f"[{elapsed:7.2f}s] {key}  {describe(value)}")
        return handler

    log(f"Czekam na {address} — naciśnij przycisk na panelu bieżni, żeby ją obudzić.")
    device = await wait_for_device(address, 180.0)
    if device is None:
        log("Nie odezwała się przez trzy minuty.")
        return
    log("Znalazłem. Łączę...")
    async with BleakClient(device, timeout=30.0) as client:
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

        if do_start:
            log("\nUruchamiam taśmę...")
            await control(client, 0x00)                                        # przejmij sterowanie
            await control(client, 0x07)                                        # start
            await control(client, 0x03, round(incline * 10).to_bytes(2, "little", signed=True))
            log("Start przyjęty. Wejdź na taśmę i idź, licząc kroki.\n")
            # Prędkość zadana od razu po starcie bywa ignorowana — bieżnia
            # rozpędza się do 1 km/h i dopiero wtedy przyjmuje cel. Stąd trzy
            # próby w odstępach.
            for attempt in range(3):
                await asyncio.sleep(8.0)
                log(f"Zadaję {speed} km/h (próba {attempt + 1})")
                await control(client, 0x02, round(speed * 100).to_bytes(2, "little"))

        try:
            await asyncio.sleep(seconds)
        except asyncio.CancelledError:
            pass

        if do_start:
            log("\nZatrzymuję taśmę.")
            try:
                await control(client, 0x08, bytes([0x01]))
            except Exception as exc:
                log(f"zatrzymanie nieudane: {exc}")

        log("\n=== PODSUMOWANIE ===")
        for uuid, count in sorted(counts.items(), key=lambda kv: -kv[1]):
            log(f"{uuid}  {count} pakietów, ostatni: {last[uuid].hex(' ')}")


async def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--address", help="adres bieżni; bez tego tylko skan")
    parser.add_argument("--seconds", type=float, default=120.0, help="jak długo słuchać")
    parser.add_argument("--scan-seconds", type=float, default=12.0)
    parser.add_argument("--start", action="store_true", help="uruchom taśmę i zatrzymaj na koniec")
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
