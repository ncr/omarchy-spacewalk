import QtQuick
import QtQuick.Layouts
import org.kde.kirigami as Kirigami
import "../plasmoid/contents/ui" as Widget
import "../plasmoid/contents/code/Settings.js" as Settings
import "../plasmoid/contents/code/Goal.js" as Goal

// The widget's parts outside plasmashell, for test_plasmoid.py: a client on
// the session bus (the tests point it at a private one), the popup, and the
// panel number. main.qml and the settings page need the shell; plasmoidviewer
// covers those.
Item {
    id: harness
    width: 380
    height: full.height + compact.height + 20

    property alias client: spacewalk
    property alias full: full
    property alias compact: compact
    property alias plasmoidStub: plasmoidStub

    // What the Plasma popup would paint under the views.
    Rectangle {
        anchors.fill: parent
        color: Kirigami.Theme.backgroundColor
    }

    Widget.SpacewalkClient { id: spacewalk }

    // Stands in for the PlasmoidItem the compact view toggles.
    QtObject {
        id: plasmoidStub
        property bool expanded: false
    }

    Widget.FullRepresentation {
        id: full
        objectName: "full"
        width: 360
        height: implicitHeight
        client: spacewalk
    }

    Widget.CompactRepresentation {
        id: compact
        objectName: "compact"
        y: full.height + 10
        width: Layout.preferredWidth > 0 ? Layout.preferredWidth : 120
        height: 32
        client: spacewalk
        plasmoidItem: plasmoidStub
    }

    function bridgeArgs(cfg) { return Settings.bridgeArgs(cfg) }
    function goalCall(name, args) { return Goal[name].apply(null, args) }

    // The settings page, without the dialog around it; out of sight, out of
    // the way of the clicks on the views. Plasma hands the settings over as
    // initial properties, so these do too.
    function settingsPage(settings) {
        var component = Qt.createComponent("../plasmoid/contents/ui/configGeneral.qml")
        if (component.status !== Component.Ready) console.warn(component.errorString())
        var props = { x: -10000 }
        for (var key in settings) props["cfg_" + key] = settings[key]
        return component.createObject(harness, props)
    }

    // A second client on a name nobody owns: how the widget looks without the bridge.
    function orphanClient() {
        return Qt.createQmlObject('import "../plasmoid/contents/ui" as Widget; Widget.SpacewalkClient { busName: "io.github.ncr.NobodyHere" }',
                                  harness, "orphan")
    }
}
