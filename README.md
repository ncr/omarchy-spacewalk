# Spacewalk

This drives my treadmill — a **Urevo SpaceWalk 3S** under my desk — from the
[Omarchy](https://omarchy.org) bar, in place of the vendor's phone app.
Written for my own setup, in the malleable computing spirit. Steps and goal
progress in the bar; calories, time, distance, a history grid and
speed / incline / belt control in the panel.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="docs/hero-dark.webp">
  <img src="docs/hero-light.webp" alt="The Omarchy bar with the step counter pill and the Spacewalk panel open: today's numbers, a history grid, and speed and incline controls; the picture cycles through a few Omarchy themes" width="100%">
</picture>

Verified only on my pad, but the treadmill side is standard Bluetooth FTMS
(`0x1826`), so others may largely work. Steps are the one vendor-specific
part ([docs/gatt-dump.md](docs/gatt-dump.md)); `strideMeters` derives them
from distance elsewhere. Got a **KingSmith WalkingPad**? Use
[msegoviadev/omarchy-walkingpad](https://github.com/msegoviadev/omarchy-walkingpad)
or
[shllg/omarchy-walkingpad-control](https://github.com/shllg/omarchy-walkingpad-control)
instead — both good.

## Install

```bash
sudo pacman -S python-bleak     # the only dependency beyond base Omarchy
omarchy plugin add https://github.com/ncr/omarchy-spacewalk.git --enable
```

Add the **Spacewalk** widget to the bar (Setup > Plugins) and power-cycle the
treadmill — it advertises only briefly, and it takes one connection at a
time, so keep the Urevo phone app closed. `./probe.py` finds its address;
put it in the widget settings to skip scanning on every connect.

Remove with `omarchy plugin remove io.github.ncr.spacewalk`; the day history
lives in `~/.local/state/omarchy-spacewalk/`.

## Use

Click the pill for the panel; middle-click starts or stops the belt. Only
midnight resets the day counter — the bridge sums increments across walks, so
the treadmill clearing its own counters on stop changes nothing. With the
belt stopped, the panel shows the values to apply on start.

Settings: `address`, `dailyGoal` (10000), `startSpeed` (2.5 km/h),
`startIncline` (3%), `strideMeters` (0 = steps from the treadmill),
`phonePort` (0 = Apple Health sync off; set it — say 8787 — and walks flow to
an iPhone over Tailscale via Shortcuts, see
[docs/apple-health.md](docs/apple-health.md)).

## When it sulks

The bridge rescans and reconnects by itself. When reconnecting jams anyway:
`bluetoothctl disconnect <address>`, `pkill -f spacewalk-bridge.py`, or flip
the treadmill's power switch. To watch it live:

```bash
python3 ~/.config/omarchy/plugins/io.github.ncr.spacewalk/spacewalk-bridge.py --address <address>
```

Commands on stdin: `start`, `stop`, `speed 2.5`, `incline 3`. After editing
plugin files, `omarchy-restart-shell`; peek with `omarchy-shell spacewalk dump`.

## Who this is for

Honestly — I built this for my own desk and don't expect anyone else to run
it, though maybe one or two people with the same pad will turn up. If that's
you, or you just enjoy this kind of thing, follow me on
[X](https://x.com/JacekBecela) — more of it coming.

## License

[MIT](LICENSE)
