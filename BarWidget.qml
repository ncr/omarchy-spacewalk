import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Pigułka na barze: ikona, kroki dnia, cienki pasek postępu do celu.
// Klik otwiera panel; kliknięcie środkowym startuje albo zatrzymuje taśmę.
BarWidget {
  id: root
  moduleName: "ncr.treadmill"

  readonly property var service: bar && bar.shell ? bar.shell.serviceFor("ncr.treadmill") : null
  readonly property int goal: service ? service.dailyGoal : 10000
  readonly property int steps: service ? service.daySteps : 0
  readonly property real progress: Model.progress(steps, goal)

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = pill
    if ("hostWidget" in target) target.hostWidget = root
    if ("service" in target) target.service = root.service
  }

  function pushSettings() {
    if (service && typeof service.applySettings === "function") service.applySettings(root.settings)
  }

  function togglePanel() {
    if (panelLoader.item && panelLoader.item.toggle) panelLoader.item.toggle()
  }

  readonly property bool opened: panelLoader.item ? panelLoader.item.opened === true : false
  function open() { if (panelLoader.item && panelLoader.item.openFromHotkey) panelLoader.item.openFromHotkey() }
  function close() { if (panelLoader.item && panelLoader.item.close) panelLoader.item.close() }

  readonly property bool popoutSwitchClosing: panelLoader.item ? panelLoader.item.popoutSwitchClosing === true : false
  function closeForPopoutSwitch() { if (panelLoader.item) panelLoader.item.closeForPopoutSwitch() }

  implicitWidth: pill.implicitWidth
  implicitHeight: bar ? bar.barSize : pill.implicitHeight

  onBarChanged: { injectPanel(); pushSettings() }
  onSettingsChanged: { injectPanel(); pushSettings() }
  onServiceChanged: { injectPanel(); pushSettings() }

  Loader {
    id: panelLoader
    active: true
    source: Qt.resolvedUrl("Panel.qml")
    visible: false
    onLoaded: {
      root.injectPanel()
      Qt.callLater(root.injectPanel)
    }
  }

  Item {
    id: pill
    anchors.fill: parent
    implicitWidth: content.implicitWidth + Style.space(17)
    implicitHeight: parent ? parent.height : Style.space(24)

    Column {
      id: content
      anchors.centerIn: parent
      spacing: Style.space(2)

      Row {
        spacing: Style.space(6)
        anchors.horizontalCenter: parent.horizontalCenter

        Text {
          text: root.service && root.service.walking ? "󰗇" : "󰖃"
          color: root.bar ? root.bar.barForeground : Color.foreground
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.icon
          opacity: root.service && root.service.connected ? 1.0 : 0.45
        }

        Text {
          text: Model.formatSteps(root.steps)
          color: root.bar ? root.bar.barForeground : Color.foreground
          font.family: root.bar ? root.bar.fontFamily : Style.font.family
          font.pixelSize: Style.font.body
        }
      }

      // Pasek do celu — cienki, żeby nie rozpychał baru.
      Rectangle {
        width: content.width
        height: Style.space(2)
        radius: height / 2
        color: Qt.rgba(1, 1, 1, 0.18)

        Rectangle {
          width: parent.width * root.progress
          height: parent.height
          radius: parent.radius
          color: root.progress >= 1 ? (root.bar ? root.bar.urgent : Color.urgent)
                                    : (root.bar ? root.bar.barForeground : Color.foreground)
        }
      }
    }

    MouseArea {
      anchors.fill: parent
      acceptedButtons: Qt.LeftButton | Qt.MiddleButton
      hoverEnabled: true
      onClicked: function(mouse) {
        if (!root.service) return
        if (mouse.button === Qt.MiddleButton) {
          if (root.service.walking) root.service.stop()
          else root.service.start()
        } else {
          root.togglePanel()
        }
      }
    }
  }
}
