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
    implicitWidth: pillRow.implicitWidth + Style.space(17)
    implicitHeight: parent ? parent.height : Style.space(24)

    // Rząd jest wyśrodkowany sam, a pasek postępu wisi pod nim na kotwicy do
    // dołu. Wspólna kolumna centrowałaby rząd RAZEM z paskiem, przez co tekst
    // i ikona siedziały wyżej niż środek baru — i skakały, gdy pasek się
    // pojawiał albo znikał.
    Row {
      id: pillRow
      anchors.centerIn: parent
      spacing: Style.space(6)
      height: Math.max(icon.implicitHeight, stepsText.implicitHeight)

      Text {
        id: icon
        anchors.verticalCenter: parent.verticalCenter
        text: root.service && root.service.walking ? "󰗇" : "󰖃"
        color: root.bar ? root.bar.barForeground : Color.foreground
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.body + 2
        opacity: root.service && root.service.connected ? 1.0 : 0.45
      }

      Text {
        id: stepsText
        anchors.verticalCenter: parent.verticalCenter
        text: Model.formatSteps(root.steps)
        color: root.bar ? root.bar.barForeground : Color.foreground
        font.family: root.bar ? root.bar.fontFamily : Style.font.family
        font.pixelSize: Style.font.body
      }
    }

    // Postęp do celu: sama wypełniona część, bez szarej ścieżki pod spodem —
    // pusta ścieżka na całej szerokości czytała się jak podkreślenie pigułki.
    Rectangle {
      anchors.horizontalCenter: pillRow.horizontalCenter
      anchors.top: pillRow.bottom
      anchors.topMargin: Style.space(2)
      width: pillRow.width * root.progress
      height: Style.space(2)
      radius: height / 2
      visible: root.progress > 0
      color: root.progress >= 1 ? (root.bar ? root.bar.urgent : Color.urgent)
                                : (root.bar ? root.bar.barForeground : Color.foreground)
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
