# Spacewalk for KDE Plasma

The Omarchy widget's panel number and popup as a Plasma 6 widget: today's
steps in the panel — or distance, or calories, whichever the daily goal
counts; the rest of the day's numbers, the heart rate chart, thirteen weeks
of history and speed / incline / belt control in the popup. Under it
runs the same Bluetooth bridge as on Omarchy, as a systemd user service on
the D-Bus session bus ([docs/dbus.md](../docs/dbus.md)).

## Install

```bash
sudo apt install python3-bleak      # or: sudo pacman -S python-bleak
kde/install.sh
```

That installs and starts `spacewalk-widget.service`, and installs the widget
in `~/.local/share/plasma/plasmoids`. Then right-click a panel, **Add or
Manage Widgets**, and drag **Spacewalk** onto it. Run `kde/install.sh` again
after pulling changes; it upgrades both, and says when plasmashell needs a
restart to load the new widget. `kde/install.sh uninstall` removes both; the
step history in `~/.local/state/omarchy-spacewalk/` stays.

Power-cycle the treadmill if it does not show up: it advertises only briefly,
and it takes one connection at a time, so keep the Urevo phone app closed.

## Use

| Where | What |
|---|---|
| Panel | the walker and today's steps, distance or calories — what the goal counts — dimmed while the treadmill is away |
| Left click | opens the popup |
| Middle click | starts the belt, or stops it |
| Right click | start / pause, stop, what the goal counts, what is left instead of what is done, reconnect, settings |
| Popup switch | starts the belt, or pauses it — flip it back to resume |
| Popup arrows | speed ±0.5 km/h, incline ±1 %; with the belt stopped they set what it starts with |
| Day grid | hover a day to see its numbers |
| Heart chart | hover to read a point or a note; the wheel zooms |
| **R** in the popup | restarts the bridge and the Bluetooth link; the belt is left alone |

The settings (right click, **Configure Spacewalk…**) are the Omarchy
widget's: daily goal, treadmill address, speed and incline on start, stride
length, heart rate strap and limit, Apple Health sync port. All but the goal
go to the bridge, which restarts only when they change.

The goal can count steps (10 000 by default), distance (5 km) or calories
(400 kcal); each kind keeps its own goal, so switching back finds the old
one. The panel number, the big number in the popup, the progress bar, its
forecast, the day grid's colours and the average all follow the choice; the
row under the big number shows the other two and the time. The calorie
forecast with the belt stopped assumes the calories a metre the treadmill
has counted so far.

## How it is put together

```
kde/
  install.sh                 service + widget, install / upgrade / uninstall
  install-service.sh         the service alone
  spacewalk-widget.service.in, io.github.ncr.Spacewalk.service
  plasmoid/                  the widget package (kpackagetool6)
    metadata.json
    contents/config/         main.xml (settings), config.qml
    contents/code/Model.js   the Omarchy widget's Model.js, copied
    contents/code/Settings.js  settings → the bridge's command line
    contents/code/Goal.js    the goal in steps, distance or calories
    contents/ui/main.qml     PlasmoidItem: tooltip, menu, settings → Configure
    contents/ui/SpacewalkClient.qml   the D-Bus face as properties, like Service.qml
    contents/ui/CompactRepresentation.qml, FullRepresentation.qml, HeartChart.qml, Walker.qml
    contents/ui/configGeneral.qml
  tests/                     test_plasmoid.py, Harness.qml, fake_host.py
```

`FullRepresentation.qml` and `HeartChart.qml` are ports of `Panel.qml` and
`HeartChart.qml`; `Model.js` is shared word for word (a test checks the copy).

## Developing

```bash
python3 -m unittest -v test_spacewalk.py               # bridge, host, D-Bus
python3 -m unittest discover -s kde/tests -v           # the widget
SPACEWALK_SHOTS=/tmp/shots QT_QPA_PLATFORMTHEME=kde \
    python3 -m unittest discover -s kde/tests          # ... and pictures of it
```

The widget tests run its parts outside plasmashell — offscreen, through
`tests/Harness.qml` — against a fake bridge on a private D-Bus bus
(`tests/fake_host.py`), never a treadmill. They need PyQt6 with QtQuick and
QtTest, Plasma 6's QML modules and `dbus-daemon`.

`main.qml` and the settings page need a Plasma shell. To see the installed
widget without touching your panels:

```bash
kde/install.sh
plasmoidviewer -a io.github.ncr.spacewalk -s 440x900               # the popup, on a desktop
plasmoidviewer -c org.kde.panel -a io.github.ncr.spacewalk \
    -f horizontal -l bottomedge                                     # in a panel
systemctl --user restart plasma-plasmashell                         # reload it in your panels
```

Things learned the hard way, all in comments where they matter:

- Plasma's D-Bus module hands properties over wrapped on the first read and
  plain on every change; `SpacewalkClient.read()` takes both.
- A D-Bus call from QML must not set `signature`, or it goes out without its
  arguments.
- Inside a representation, `client: client` binds the property to itself, not
  to an id of that name — hence the id `spacewalk` in `main.qml`.
- `kpackagetool6 --packageroot` works for `--install` only; `--upgrade` and
  `--remove` look in your own plasmoids whatever it says.
- The bridge confirms every speed and incline change; taken at once, a late
  confirmation pulled the tile back under a quick second click.
