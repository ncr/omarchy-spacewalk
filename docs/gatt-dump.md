# What the Urevo SpaceWalk 3S exposes

Collected with `probe.py` on 2026-08-31 during a real walk. Device: `54:50:00:47:91:EB`,
name `URTM024`, manufacturer UREVO, firmware V90.08.12, hardware V002.

## Services

| Service | What it is |
|---|---|
| `0x1826` Fitness Machine | what the plugin uses |
| `0x180a` Device Information | name, model, versions |
| `0xfff0` | Urevo's proprietary protocol (`fff1` notify, `fff2` write) |
| `0xfee0` | Huami (Amazfit) — unused |
| `5833ff01-9b8b-5191-6142-22a4536ef123` | proprietary, unused |

## Fitness Machine

| Characteristic | Reading | Meaning |
|---|---|---|
| `0x2acc` Feature | `5c 16 00 00 03 00 00 00` | data fields + **targets: speed and inclination supported** |
| `0x2ad4` Supported Speed Range | `64 00 58 02 0a 00` | 1.0 – 6.0 km/h, step 0.1 |
| `0x2ad5` Supported Inclination Range | `00 00 5a 00 0a 00` | 0 – 9, step 1 |
| `0x2acd` Treadmill Data | notify every 1 s | see below |
| `0x2ad9` Control Point | write + indicate | control |
| `0x2ada` Machine Status | notify | machine state changes |
| `0x2ad3` Training Status | notify | training state |

## Treadmill Data packet — 26 bytes, flags `9c 25`

Flags `0x259c` set bits 2, 3, 4, 7, 8, 10 **and 13**. Bit 13 does not exist in the
FTMS specification — Urevo put a step counter there.

| Bytes | Field | Example from the walk |
|---|---|---|
| 0–1 | flags | `9c 25` |
| 2–3 | speed, hundredths of km/h | `fa 00` → 2.50 |
| 4–6 | distance, m (10 m resolution) | `64 00 00` → 100 |
| 7–8 | inclination, tenths of % | `1e 00` → 3.0 |
| 9–10 | ramp angle | `00 00` |
| 11–14 | positive and negative elevation gain | zeros |
| 15–16 | calories | `06 00` → 6 |
| 17–19 | kcal/h, kcal/min | zeros |
| 20 | heart rate | `00` |
| 21–22 | time, s | `95 00` → 149 |
| **23–25** | **steps, uint24 — Urevo extension** | `b3 00 00` → **179** |

Proof that this is steps and not a second clock: over 130 s of walking the counter grew
to 179, i.e. 1.36/s, while the time in the same packet ticked steadily at 1.0/s. That
works out to 0.56 m per step over 100 m of distance — exactly what a slow walk at
2.5 km/h gives.

## Control — what works and what to expect

Confirmed responses from `0x2ad9`: `80 00 01` (request control), `80 07 01` (start),
`80 02 01` (speed), `80 03 01` (inclination) — all accepted.

**Speed and inclination set right after start are lost without a response.** The
treadmill first spins up to 1 km/h and only then accepts targets. The bridge waits 8 s
and retries up to four times, until the reading matches the requested value.

**A stopped belt accepts no speed or inclination commands at all** — all eight
"no response to 0x03" cases in the log are commands sent at zero speed. The bridge
remembers them as the target and re-sends after start.

**The start confirmation can take 7 seconds to arrive.** A 5 s limit turned a
successful command into an error and aborted the target re-send; the limit is now 10 s,
and a missing confirmation no longer aborts the re-send anyway — machine status
(`0x2ada`) shows `04` when the belt starts moving, `02 01` and `02 02` on stop.

## Advertising: the treadmill sleeps

The treadmill advertises only for a brief moment after power-on. Then it goes silent
and can't be found either by address or by scanning — the only way out is to flip the
power switch. That's why the bridge doesn't poll periodically but **scans
continuously** and grabs the device the moment it speaks up.

A phone with the Urevo app wins that race: once it connects, the treadmill stops
advertising to anyone else. Bluetooth on the phone must stay off while working with
the plugin.
