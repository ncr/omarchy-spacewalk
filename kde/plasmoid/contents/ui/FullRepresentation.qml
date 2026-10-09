import QtQuick
import QtQuick.Controls as QQC2
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import "../code/Model.js" as Model
import "../code/Goal.js" as Goal

// The popup: today's numbers, the switch that runs the belt, the heart rate
// chart, thirteen weeks of history and the speed and incline tiles. A port of
// the Omarchy widget's Panel.qml to Plasma; everything comes in through
// properties, so it also runs outside the shell (kde/tests).
Item {
    id: root

    property var client: null
    // What the goal counts (Goal.KINDS), and the goal in its unit: steps,
    // metres or kcal.
    property string goalKind: "steps"
    property real goal: 10000
    property real strideMeters: 0
    property real startSpeed: 2.5
    // The popup is showing: timers and the live chart run only then.
    property bool opened: true

    function sp(n) { return Math.round(n * Kirigami.Units.gridUnit / 18) }
    function alpha(c, a) { return Qt.rgba(c.r, c.g, c.b, a) }

    readonly property color fg: Kirigami.Theme.textColor
    readonly property color accent: Kirigami.Theme.highlightColor
    readonly property color urgent: Kirigami.Theme.negativeTextColor
    readonly property real bigPoints: Kirigami.Theme.defaultFont.pointSize * 3.6
    readonly property real subtitlePoints: Kirigami.Theme.defaultFont.pointSize * 1.3

    Layout.minimumWidth: sp(360)
    Layout.preferredWidth: sp(360)
    Layout.maximumWidth: sp(360)
    Layout.minimumHeight: column.implicitHeight
    Layout.preferredHeight: column.implicitHeight
    implicitWidth: sp(360)
    implicitHeight: column.implicitHeight

    // The cell under the cursor swaps the numbers up top to that day; leaving the
    // grid goes back to today. No clicking — peeking at history is a mouse motion,
    // not a choice you would have to undo.
    property var hoveredDay: null
    readonly property string selectedDay: hoveredDay ? hoveredDay.key : ""
    readonly property string todayKey: client && client.today !== "" ? client.today : Model.dayKey(new Date())
    readonly property bool showingToday: selectedDay === "" || selectedDay === todayKey
    readonly property var selectedRecord: {
        if (showingToday || !client || !client.history) return null
        return client.history[selectedDay] || { steps: 0, distance_m: 0, kcal: 0, elapsed_s: 0 }
    }

    readonly property var shownRecord: selectedRecord ? selectedRecord
        : (client ? { steps: client.daySteps, distance_m: client.dayDistanceM,
                      kcal: client.dayKcal, elapsed_s: client.dayElapsedS }
                  : { steps: 0, distance_m: 0, kcal: 0, elapsed_s: 0 })
    // What counts toward the goal on the shown day.
    readonly property real amount: Goal.value(goalKind, shownRecord)
    readonly property real progress: Model.progress(amount, goal)

    // Pace from the last minute; with the belt stopped, a forecast for the set speed.
    readonly property real perMinute: {
        if (!client) return 0
        var live = Goal.paceFromSamples(goalKind, client.paceOld, client.paceNew)
        if (live > 0) return live
        return Goal.paceFromSpeed(goalKind, client.speed > 0 ? client.speed : startSpeed, strideMeters,
                                  client.history)
    }

    property var clockNow: new Date()
    Timer {
        running: root.opened
        interval: 10000
        repeat: true
        triggeredOnStart: true
        onTriggered: root.clockNow = new Date()
    }

    // The same line for today and for the previewed day — hiding it on a grid
    // hover shortened the popup and everything below it jumped.
    readonly property string caption: showingToday
        ? Goal.caption(goalKind, amount, goal, perMinute, clockNow)
        : Goal.pastDayCaption(goalKind, amount, goal)

    // Trouble is described matter-of-factly; every state names the device it
    // is about — with a strap there are two links.
    readonly property string problemLabel: {
        if (!client) return "no service"
        if (client.reconnecting) return "restarting the bridge..."
        switch (client.linkState) {
            case "no_service": return "bridge not running — kde/install-service.sh"
            case "starting": return "starting the bridge..."
            case "releasing": return "dropping a stale treadmill link..."
            case "scanning": return "looking for the treadmill..."
            case "found": return "treadmill found..."
            case "connecting": return "connecting to the treadmill..."
            case "not_found": return "treadmill out of reach — flip its power switch"
            case "disconnected": return "treadmill disconnected"
            case "stopping": return "bridge shutting down..."
            // Looking for a strap is not shown: without one it would come up
            // every minute for good.
            case "connected": return client.heartState === "connecting" ? "connecting to the strap..." : ""
            default: return client.linkState
        }
    }

    // When all is well a carousel of phrases runs under the title — one set
    // for a moving belt, another for a standing one.
    readonly property var walkingPhrases: [
        "You are walking", "Legs doing the work", "The desk sits, you do not",
        "Step by step to 10k", "Belt under control", "Legs earning the chair"
    ]
    readonly property var pausedPhrases: [
        "Stepped off the belt", "The belt is waiting", "Counter on hold", "Short break, right?"
    ]
    readonly property var idlePhrases: [
        "Treadmill ready", "Waiting for the switch", "Zero steps will not grow", "Incline set, your move"
    ]
    readonly property var phrases: {
        if (!client || problemLabel !== "") return []
        if (client.walking) return walkingPhrases
        return client.paused ? pausedPhrases : idlePhrases
    }
    onPhrasesChanged: phraseIndex = 0

    property int phraseIndex: 0
    readonly property bool rotating: opened && phrases.length > 1
    readonly property string heroMeta: problemLabel !== ""
        ? problemLabel
        : (phrases.length > 0 ? phrases[phraseIndex % phrases.length] : "")

    Timer {
        interval: 2800
        running: root.rotating
        repeat: true
        onTriggered: phraseSwap.restart()
    }

    SequentialAnimation {
        id: phraseSwap
        PropertyAnimation { target: heroMetaLabel; property: "opacity"; to: 0.0; duration: 180; easing.type: Easing.OutQuad }
        ScriptAction { script: root.phraseIndex = root.phraseIndex + 1 }
        PropertyAnimation { target: heroMetaLabel; property: "opacity"; to: 0.7; duration: 220; easing.type: Easing.InQuad }
    }
    // An animation cut off midway would leave the phrase half faded out.
    onRotatingChanged: if (!rotating) { phraseSwap.stop(); heroMetaLabel.opacity = 0.7 }

    readonly property int gridWeeks: 13
    readonly property var gridModel: client && opened ? Model.gridDays(client.history, new Date(), gridWeeks) : []
    readonly property bool hasHistory: client && client.history ? Object.keys(client.history).length > 0 : false

    // The heart rate section shows up with the first reading of the day, or
    // with a strap in reach. Without a strap the popup is what it was before.
    readonly property bool hasHeart: client
        ? client.heartPoints.length > 0 || client.heartState === "connected" || client.heartState === "connecting"
        : false

    readonly property string hoveredLabel: hoveredDay ? Model.formatDay(hoveredDay.date) : ""

    // Four fill levels from the text colour, and the accent for a day that
    // reached the goal.
    function levelColor(level) {
        switch (level) {
            case 0: return alpha(fg, 0.10)
            case 1: return alpha(fg, 0.28)
            case 2: return alpha(fg, 0.48)
            case 3: return alpha(fg, 0.70)
            default: return accent
        }
    }

    // The switch starts the belt and pauses it, so flipping it back resumes at
    // the set speed and incline instead of ending the workout. A full stop is
    // on the panel icon's middle click and in its menu.
    function toggleBelt() {
        if (!client) return
        if (client.walking) client.pause()
        else client.start()
    }

    readonly property bool beltBusy: client
        && (client.commandPending
            || ["sending", "control", "starting", "unconfirmed", "spinup", "setting"].indexOf(client.phaseName) !== -1)
    // Optimistic: the moment you press, the knob throws to where the belt is headed.
    readonly property bool switchOn: client
        ? (client.commandPending ? client.intendedWalking : client.walking) : false

    // The tiles show the TARGET value, not the momentary reading: stepping off
    // the belt you saw 1 km/h mid-braking though the target was 2.5.
    readonly property real shownSpeed: client ? client.targetSpeed : 0
    readonly property real shownIncline: client ? client.targetIncline : 0

    function bumpSpeed(delta) {
        if (!client) return
        // The treadmill supports 1.0–6.0 km/h in 0.1 steps (its own declaration).
        client.setSpeed(Math.max(1.0, Math.min(6.0, Math.round((shownSpeed + delta) * 10) / 10)))
    }

    function bumpIncline(delta) {
        if (!client) return
        // Incline 0–9 in steps of 1.
        client.setIncline(Math.max(0, Math.min(9, Math.round(shownIncline + delta))))
    }

    // R restarts the bridge and the Bluetooth link; the belt is left alone.
    focus: true
    onOpenedChanged: if (opened) forceActiveFocus()
    Keys.onReleased: function(event) {
        if (event.key === Qt.Key_R && !event.isAutoRepeat
            && (event.modifiers === Qt.NoModifier || event.modifiers === Qt.ShiftModifier)) {
            if (root.client) root.client.reconnect()
            event.accepted = true
        }
    }

    // In a panel the popup takes the size asked for above; on the desktop the
    // widget can be given less, and then it scrolls instead of spilling out.
    PlasmaComponents.ScrollView {
        id: scroller
        anchors.fill: parent
        contentWidth: availableWidth
        // Never sideways: content as wide as the view would otherwise loop
        // with the scroll bar's own visibility.
        QQC2.ScrollBar.horizontal.policy: QQC2.ScrollBar.AlwaysOff

        Column {
            id: column
            width: scroller.availableWidth
            spacing: root.sp(14)
            topPadding: root.sp(8)
            bottomPadding: root.sp(8)

            // ---- header: what the treadmill is doing, and the switch that runs it
            RowLayout {
                x: root.sp(8)
                width: parent.width - root.sp(16)
                spacing: root.sp(10)

                Walker {
                    Layout.preferredWidth: Kirigami.Units.iconSizes.medium
                    Layout.preferredHeight: Kirigami.Units.iconSizes.medium
                    opacity: root.client && root.client.connected ? 1.0 : 0.5
                }

                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 0
                    Kirigami.Heading {
                        Layout.fillWidth: true
                        level: 3
                        text: "Spacewalk 3S"
                        elide: Text.ElideRight
                    }
                    PlasmaComponents.Label {
                        id: heroMetaLabel
                        objectName: "heroMeta"
                        Layout.fillWidth: true
                        text: root.heroMeta.toUpperCase()
                        font: Kirigami.Theme.smallFont
                        opacity: 0.7
                        elide: Text.ElideRight
                    }
                }

                PlasmaComponents.Switch {
                    id: beltSwitch
                    objectName: "beltSwitch"
                    checked: root.switchOn
                    enabled: root.client !== null && root.client.connected
                    // Clicking breaks the binding to `checked`; put it back, the
                    // belt's state decides.
                    onToggled: {
                        root.toggleBelt()
                        checked = Qt.binding(function() { return root.switchOn })
                    }
                    QQC2.ToolTip.visible: hovered
                    QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                    QQC2.ToolTip.text: root.client && root.client.walking
                        ? "Pauses the belt; flip again to resume"
                        : (root.client && root.client.paused
                           ? "Resumes at the set speed and incline"
                           : "Starts at the set speed and incline")

                    // The wait shows as a pulse: it starts the instant the command
                    // goes out and stops when the belt reaches the new state.
                    SequentialAnimation on opacity {
                        running: root.beltBusy
                        loops: Animation.Infinite
                        alwaysRunToEnd: true
                        NumberAnimation { to: 0.35; duration: 450; easing.type: Easing.InOutSine }
                        NumberAnimation { to: 1.0; duration: 450; easing.type: Easing.InOutSine }
                    }
                }
            }

            // ---- what the goal counts: the main number, full width so it does not twitch
            PlasmaComponents.Label {
                objectName: "amount"
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                text: Goal.format(root.goalKind, root.amount)
                font.pointSize: root.bigPoints
                font.bold: true
            }

            // ---- progress bar and when the goal falls
            Column {
                width: parent.width
                spacing: root.sp(6)

                Rectangle {
                    x: root.sp(16)
                    width: parent.width - root.sp(32)
                    height: root.sp(8)
                    radius: height / 2
                    color: root.alpha(root.fg, 0.15)

                    Rectangle {
                        objectName: "progressFill"
                        width: parent.width * root.progress
                        height: parent.height
                        radius: parent.radius
                        color: root.progress >= 1 ? root.urgent : root.accent
                        // Short: hovering the grid changes it every few tens of milliseconds.
                        Behavior on width { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
                    }
                }

                PlasmaComponents.Label {
                    objectName: "caption"
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: root.caption
                    opacity: 0.7
                }
            }

            // ---- the rest of the day — steps, calories, distance, whichever two
            // the goal does not count, and the time: three equal columns, so a
            // changing digit count does not shift them sideways
            Row {
                id: statsRow
                width: parent.width
                readonly property real cellWidth: width / 3

                Repeater {
                    model: Goal.stats(root.goalKind, root.shownRecord)
                    Column {
                        required property var modelData
                        width: statsRow.cellWidth
                        spacing: root.sp(2)
                        PlasmaComponents.Label {
                            objectName: "stat-" + modelData.label
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            elide: Text.ElideRight
                            text: modelData.value
                            font.pointSize: root.subtitlePoints
                        }
                        PlasmaComponents.Label {
                            width: parent.width
                            horizontalAlignment: Text.AlignHCenter
                            elide: Text.ElideRight
                            text: modelData.label.toUpperCase()
                            opacity: 0.55
                            font: Kirigami.Theme.smallFont
                        }
                    }
                }
            }

            Kirigami.Separator { width: parent.width }

            // ---- heart rate: today's chart, with the bridge's notes pinned to it
            Column {
                objectName: "heartSection"
                visible: root.hasHeart
                width: parent.width
                spacing: root.sp(6)

                // The point under the cursor, otherwise the live rate.
                PlasmaComponents.Label {
                    objectName: "heartCaption"
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    text: heartChart.hoverPoint
                          ? Model.heartCaption(heartChart.hoverPoint)
                          : (root.client ? Model.heartSummary(root.client.heartPoints, root.client.heartBpm,
                                                               root.client.heartState, root.client.heartDevice) : "")
                            + (heartChart.zoomLabel !== "" ? " · " + heartChart.zoomLabel : "")
                    opacity: 0.75
                    font: Kirigami.Theme.smallFont
                }

                HeartChart {
                    id: heartChart
                    x: root.sp(16)
                    width: parent.width - root.sp(32)
                    height: implicitHeight
                    // Bound only while the popup is open: a point arrives every
                    // second, and a closed popup has nobody to redraw for.
                    points: root.client && root.opened ? root.client.heartPoints : []
                    notes: root.client && root.opened ? root.client.heartNotes : []
                }
            }

            Kirigami.Separator { visible: root.hasHeart; width: parent.width }

            // ---- grid of the last 13 weeks
            Column {
                width: parent.width
                spacing: root.sp(6)

                // Only the date of the day under the cursor; the row keeps its
                // height even when empty, so the grid does not jump.
                PlasmaComponents.Label {
                    width: parent.width
                    height: Math.round(hoveredMetrics.height * 1.3)
                    horizontalAlignment: Text.AlignHCenter
                    verticalAlignment: Text.AlignVCenter
                    text: root.hoveredLabel
                    opacity: 0.75
                    font: Kirigami.Theme.smallFont
                    FontMetrics { id: hoveredMetrics; font: Kirigami.Theme.smallFont }
                }

                Grid {
                    id: dayGrid
                    objectName: "dayGrid"
                    anchors.horizontalCenter: parent.horizontalCenter
                    // Guard over the whole grid: on a fast move a cell's own exit can
                    // fail to arrive and the last previewed day would stick.
                    HoverHandler { onHoveredChanged: if (!hovered) root.hoveredDay = null }
                    rows: 7
                    columns: root.gridWeeks
                    flow: Grid.TopToBottom
                    spacing: root.sp(3)

                    Repeater {
                        model: root.gridModel

                        Rectangle {
                            required property var modelData
                            width: root.sp(13)
                            height: width
                            radius: root.sp(3)
                            opacity: modelData.future ? 0.25 : 1.0
                            color: root.levelColor(Model.dayLevel(Goal.value(root.goalKind, modelData), root.goal))
                            // The previewed day outlined in the text colour, today in
                            // the negative colour; the preview governs the numbers.
                            border.width: modelData.key === root.selectedDay ? 2 : (modelData.key === root.todayKey ? 1 : 0)
                            border.color: modelData.key === root.selectedDay ? root.fg : root.urgent

                            MouseArea {
                                anchors.fill: parent
                                hoverEnabled: true
                                onEntered: root.hoveredDay = modelData
                                // Only its own exit: crossing between cells interleaves
                                // the signals.
                                onExited: if (root.hoveredDay === modelData) root.hoveredDay = null
                            }
                        }
                    }
                }

                // Average over walking days — one number that sums up the grid.
                PlasmaComponents.Label {
                    objectName: "average"
                    width: parent.width
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    visible: root.hasHistory
                    text: root.client ? Goal.averageText(root.goalKind, root.client.history) : ""
                    opacity: 0.55
                    font: Kirigami.Theme.smallFont
                }

                PlasmaComponents.Label {
                    anchors.horizontalCenter: parent.horizontalCenter
                    visible: !root.hasHistory
                    text: "History starts with your first walk"
                    opacity: 0.5
                    font: Kirigami.Theme.smallFont
                }
            }

            Kirigami.Separator { width: parent.width }

            // ---- controls: two tiles, arrows next to the value
            Row {
                anchors.horizontalCenter: parent.horizontalCenter
                spacing: root.sp(10)

                Repeater {
                    model: [
                        { kind: "speed", value: root.shownSpeed.toFixed(1) + " km/h" },
                        // The treadmill reports incline in percent (0–9%).
                        { kind: "incline", value: String(Math.round(root.shownIncline)) + "%" }
                    ]

                    Rectangle {
                        required property var modelData
                        width: Math.round((column.width - root.sp(42)) / 2)
                        height: tileRow.implicitHeight + root.sp(10)
                        radius: root.sp(8)
                        color: root.alpha(root.fg, 0.07)

                        RowLayout {
                            id: tileRow
                            anchors.fill: parent
                            anchors.margins: root.sp(4)
                            spacing: root.sp(4)

                            PlasmaComponents.ToolButton {
                                objectName: modelData.kind + "-down"
                                text: "−"
                                enabled: root.client !== null
                                onClicked: modelData.kind === "speed" ? root.bumpSpeed(-0.5) : root.bumpIncline(-1)
                                QQC2.ToolTip.visible: hovered
                                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                                QQC2.ToolTip.text: (modelData.kind === "speed" ? "0.5 km/h slower" : "Lower the incline")
                                                   + (root.client && root.client.walking ? "" : " — set once it starts")
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 0
                                PlasmaComponents.Label {
                                    objectName: modelData.kind + "-value"
                                    Layout.alignment: Qt.AlignHCenter
                                    text: modelData.value
                                    // Dimmed while the value still waits for a start.
                                    opacity: root.client && root.client.walking ? 1.0 : 0.7
                                    font.pointSize: root.subtitlePoints
                                }
                                PlasmaComponents.Label {
                                    Layout.alignment: Qt.AlignHCenter
                                    text: modelData.kind.toUpperCase()
                                    opacity: 0.5
                                    font: Kirigami.Theme.smallFont
                                }
                            }

                            PlasmaComponents.ToolButton {
                                objectName: modelData.kind + "-up"
                                text: "+"
                                enabled: root.client !== null
                                onClicked: modelData.kind === "speed" ? root.bumpSpeed(0.5) : root.bumpIncline(1)
                                QQC2.ToolTip.visible: hovered
                                QQC2.ToolTip.delay: Kirigami.Units.toolTipDelay
                                QQC2.ToolTip.text: (modelData.kind === "speed" ? "0.5 km/h faster" : "Raise the incline")
                                                   + (root.client && root.client.walking ? "" : " — set once it starts")
                            }
                        }
                    }
                }
            }

            // The latest trouble while the link is down. The bridge never clears
            // its last error, so with the treadmill connected it would only be stale.
            PlasmaComponents.Label {
                objectName: "lastError"
                x: root.sp(16)
                width: parent.width - root.sp(32)
                visible: text !== "" && !(root.client && root.client.connected)
                text: root.client ? root.client.lastError : ""
                color: root.urgent
                wrapMode: Text.Wrap
                font: Kirigami.Theme.smallFont
            }
        }
    }
}
