import QtQuick
import org.kde.plasma.plasmoid
import org.kde.plasma.core as PlasmaCore
import "../code/Model.js" as Model
import "../code/Goal.js" as Goal
import "../code/Settings.js" as Settings

// Spacewalk in the Plasma panel: the treadmill bridge's D-Bus face
// (docs/dbus.md) as a panel number and a popup.
PlasmoidItem {
    id: root

    // Not named `client`: inside the representations below, `client: client`
    // would bind each one's own property to itself.
    SpacewalkClient {
        id: spacewalk
        startSpeed: Plasmoid.configuration.startSpeed
        startIncline: Plasmoid.configuration.startIncline
    }

    // Settings go to the bridge through Configure — at load, which also starts
    // the service through D-Bus activation, and after every change. A burst
    // of edits in the settings dialog makes one call.
    readonly property var bridgeArgs: Settings.bridgeArgs(Plasmoid.configuration)
    onBridgeArgsChanged: configureLater.restart()
    Timer {
        id: configureLater
        interval: 500
        onTriggered: spacewalk.configure(root.bridgeArgs)
    }
    Component.onCompleted: configureLater.start()

    // What the goal counts, and the goal in that unit.
    readonly property string goalKind: Goal.kind(Plasmoid.configuration.goalKind)
    readonly property real goal: Goal.target(goalKind, Plasmoid.configuration)
    readonly property var today: ({ steps: spacewalk.daySteps, distance_m: spacewalk.dayDistanceM,
                                    kcal: spacewalk.dayKcal, elapsed_s: spacewalk.dayElapsedS })

    Plasmoid.icon: "speedometer"
    // In the system tray a standing belt hides in the overflow.
    Plasmoid.status: spacewalk.walking ? PlasmaCore.Types.ActiveStatus : PlasmaCore.Types.PassiveStatus

    toolTipMainText: Goal.describe(goalKind, Goal.value(goalKind, today)) + " today"
    toolTipSubText: {
        var line = Goal.stats(goalKind, today).map(function(stat) {
            return stat.label === "steps" ? stat.value + " steps" : stat.value
        }).join(" · ")
        if (spacewalk.walking)
            return line + "\nWalking at " + spacewalk.speed.toFixed(1) + " km/h"
        if (!spacewalk.connected)
            return line + "\n" + (spacewalk.linkState === "no_service" ? "The bridge is not running"
                                                                     : "Treadmill not connected")
        return line
    }

    compactRepresentation: CompactRepresentation {
        client: spacewalk
        plasmoidItem: root
        goalKind: root.goalKind
        goal: root.goal
        showRemaining: Plasmoid.configuration.showRemaining
        vertical: Plasmoid.formFactor === PlasmaCore.Types.Vertical
    }

    fullRepresentation: FullRepresentation {
        client: spacewalk
        goalKind: root.goalKind
        goal: root.goal
        strideMeters: Plasmoid.configuration.strideMeters
        startSpeed: Plasmoid.configuration.startSpeed
        opened: root.expanded
    }

    // The goal kinds in the menu, one checked at a time.
    PlasmaCore.ActionGroup {
        id: goalKinds
    }

    Plasmoid.contextualActions: [
        PlasmaCore.Action {
            text: spacewalk.walking ? "Pause the belt" : (spacewalk.paused ? "Resume the belt" : "Start the belt")
            icon.name: spacewalk.walking ? "media-playback-pause" : "media-playback-start"
            enabled: spacewalk.connected
            onTriggered: spacewalk.walking ? spacewalk.pause() : spacewalk.start()
        },
        PlasmaCore.Action {
            text: "Stop the belt"
            icon.name: "media-playback-stop"
            enabled: spacewalk.connected && (spacewalk.walking || spacewalk.paused)
            onTriggered: spacewalk.stop()
        },
        PlasmaCore.Action {
            isSeparator: true
        },
        PlasmaCore.Action {
            text: "Goal in steps"
            checkable: true
            checked: root.goalKind === "steps"
            actionGroup: goalKinds
            onTriggered: Plasmoid.configuration.goalKind = "steps"
        },
        PlasmaCore.Action {
            text: "Goal in distance"
            checkable: true
            checked: root.goalKind === "distance"
            actionGroup: goalKinds
            onTriggered: Plasmoid.configuration.goalKind = "distance"
        },
        PlasmaCore.Action {
            text: "Goal in calories"
            checkable: true
            checked: root.goalKind === "calories"
            actionGroup: goalKinds
            onTriggered: Plasmoid.configuration.goalKind = "calories"
        },
        PlasmaCore.Action {
            text: "Show " + Goal.noun(root.goalKind) + " left to the goal"
            checkable: true
            checked: Plasmoid.configuration.showRemaining
            onTriggered: function(checked) { Plasmoid.configuration.showRemaining = checked }
        },
        PlasmaCore.Action {
            isSeparator: true
        },
        PlasmaCore.Action {
            text: "Reconnect the treadmill"
            icon.name: "view-refresh"
            onTriggered: spacewalk.reconnect()
        }
    ]
}
