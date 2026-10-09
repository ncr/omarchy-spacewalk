import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import org.kde.plasma.components as PlasmaComponents
import "../code/Model.js" as Model
import "../code/Goal.js" as Goal

// The walker and today's count toward the goal in the panel: steps, distance
// or calories. Left click opens the popup, middle click starts or stops the
// belt; right click is Plasma's own menu, which also flips the number between
// done so far and left to the goal.
MouseArea {
    id: root

    property var client: null
    // Anything with an `expanded` property: the PlasmoidItem in the shell.
    property var plasmoidItem: null
    // What the goal counts (Goal.KINDS), and the goal in its unit.
    property string goalKind: "steps"
    property real goal: 10000
    property bool showRemaining: false
    // In a vertical panel the number goes under the walker.
    property bool vertical: false

    readonly property real amount: client
        ? Goal.value(goalKind, { steps: client.daySteps, distance_m: client.dayDistanceM, kcal: client.dayKcal })
        : 0
    readonly property string number: Goal.format(goalKind, showRemaining ? Model.remaining(amount, goal) : amount)

    acceptedButtons: Qt.LeftButton | Qt.MiddleButton
    hoverEnabled: true

    Layout.minimumWidth: vertical ? 0 : grid.implicitWidth
    Layout.preferredWidth: vertical ? -1 : grid.implicitWidth
    Layout.minimumHeight: vertical ? grid.implicitHeight : 0

    property bool wasExpanded: false
    onPressed: function(mouse) { wasExpanded = plasmoidItem ? plasmoidItem.expanded : false }
    onClicked: function(mouse) {
        if (mouse.button === Qt.MiddleButton) {
            if (!client || !client.connected) return
            if (client.walking) client.stop()
            else client.start()
        } else if (plasmoidItem) {
            plasmoidItem.expanded = !wasExpanded
        }
    }

    GridLayout {
        id: grid
        anchors.centerIn: parent
        columns: root.vertical ? 1 : 2
        rowSpacing: 0
        columnSpacing: Kirigami.Units.smallSpacing
        // Dimmed while the treadmill is not connected.
        opacity: root.client && root.client.connected ? 1.0 : 0.45

        Walker {
            Layout.alignment: Qt.AlignCenter
            Layout.preferredWidth: Kirigami.Units.iconSizes.smallMedium
            Layout.preferredHeight: Kirigami.Units.iconSizes.smallMedium
        }

        PlasmaComponents.Label {
            objectName: "compactNumber"
            Layout.alignment: Qt.AlignCenter
            text: root.number
            font: root.vertical ? Kirigami.Theme.smallFont : Kirigami.Theme.defaultFont
        }
    }
}
