import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Pigułka na barze: chodzik i kroki dnia w jednym napisie, pod nim cienki pasek
// postępu do celu. Klik otwiera panel; klik środkowym startuje albo zatrzymuje
// taśmę.
//
// Napis idzie przez WidgetButton — ten sam komponent, na którym stoją zegar
// i układ klawiatury. Własne liczenie wysokości stawiało pigułkę wyżej niż
// sąsiadów, bo bar układa sloty inaczej, niż wynikałoby z samego barSize.
BarWidget {
  id: root
  moduleName: "ncr.treadmill"

  readonly property var service: bar && bar.shell ? bar.shell.serviceFor("ncr.treadmill") : null
  readonly property int goal: service ? service.dailyGoal : 10000
  readonly property int steps: service ? service.daySteps : 0
  readonly property real progress: Model.progress(steps, goal)
  // Jeden stały chodzik. Drugi glif na czas marszu odpadł: w tej czcionce nie
  // ma postaci biegacza i wychodził z niego obcy znaczek. Co robi bieżnia,
  // widać w panelu.
  readonly property string glyph: "󰖃"

  function injectPanel() {
    var target = panelLoader.item
    if (!target) return
    if ("bar" in target) target.bar = root.bar
    if ("settings" in target) target.settings = root.settings
    if ("anchorItem" in target) target.anchorItem = button
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

  implicitWidth: button.implicitWidth
  implicitHeight: button.implicitHeight

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

  WidgetButton {
    id: button
    bar: root.bar
    text: root.glyph + " " + Model.formatSteps(root.steps)
    dimmed: !(root.service && root.service.connected)
    tooltipText: root.service && root.service.connected
                 ? "" : "bieżnia nieosiągalna — pstryknij wyłącznikiem"

    onPressed: function(b) {
      if (!root.service) return
      if (b === Qt.MiddleButton) {
        if (root.service.walking) root.service.stop()
        else root.service.start()
      } else {
        root.togglePanel()
      }
    }

    // Postęp do celu: sama wypełniona część, bez ścieżki pod spodem — pusta
    // ścieżka na całej szerokości czytała się jak podkreślenie pigułki.
    Rectangle {
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.bottom: parent.bottom
      anchors.bottomMargin: Style.space(5)
      width: Math.round(button.labelWidth * root.progress)
      height: Style.space(2)
      radius: height / 2
      visible: root.progress > 0
      color: root.progress >= 1 ? (root.bar ? root.bar.urgent : Color.urgent)
                                : (root.bar ? root.bar.barForeground : Color.foreground)
    }
  }
}
