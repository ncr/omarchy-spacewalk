#!/bin/sh
# Installs Spacewalk for KDE Plasma: the treadmill bridge as a systemd user
# service on D-Bus (install-service.sh) and the panel widget.
#
#   kde/install.sh             install, or upgrade what is there
#   kde/install.sh uninstall   remove both; step history stays
#
# Then add "Spacewalk" to a panel: right-click it, Add or Manage Widgets.
set -eu

here=$(cd "$(dirname "$0")" && pwd)
id=io.github.ncr.spacewalk

case "${1:-install}" in
install)
    "$here/install-service.sh" install
    if kpackagetool6 --type Plasma/Applet --show "$id" >/dev/null 2>&1; then
        kpackagetool6 --type Plasma/Applet --upgrade "$here/plasmoid"
        # plasmashell keeps the QML it has loaded until it restarts.
        echo "Upgraded the widget. To load the new version in a running panel:"
        echo "  systemctl --user restart plasma-plasmashell"
    else
        kpackagetool6 --type Plasma/Applet --install "$here/plasmoid"
        echo "Installed the widget: right-click a panel, Add or Manage Widgets, Spacewalk."
    fi
    ;;
uninstall)
    if kpackagetool6 --type Plasma/Applet --show "$id" >/dev/null 2>&1; then
        kpackagetool6 --type Plasma/Applet --remove "$id"
    fi
    "$here/install-service.sh" uninstall
    ;;
*)
    echo "usage: $0 [install|uninstall]" >&2
    exit 2
    ;;
esac
