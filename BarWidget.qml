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

  // Liczba centruje się w pełnej wysokości baru — dokładnie jak napisy
  // sąsiednich widgetów. Chodzik siedzi obok, na JEJ linii bazowej: trzymany
  // z cyframi w jednym napisie podnosił je o kilka pikseli, bo glif nerd-fonta
  // ma inne metryki niż cyfry i centrowanie liczyło jego wysokość.
  Item {
    id: button
    // Bez anchors.fill: przy pierwszym rysowaniu rodzic nie ma jeszcze wymiaru,
    // widget wychodzi zerowy, a shell wykreśla taki z układu baru.
    width: implicitWidth
    height: implicitHeight
    implicitWidth: icon.implicitWidth + Style.space(6) + number.implicitWidth + Style.space(17)
    implicitHeight: root.bar ? root.bar.barSize : Style.space(24)

    readonly property real glyphSlot: (icon.implicitWidth + Style.space(6)) / 2

    Text {
      id: number
      anchors.centerIn: parent
      anchors.horizontalCenterOffset: button.glyphSlot
      // Bar nie trzyma jednej linii — wbudowany zegar siedzi o piksel niżej niż
      // geometryczny środek slotu. Równamy do niego, bo to on wyznacza rytm baru.
      anchors.verticalCenterOffset: 1
      text: Model.formatSteps(root.steps)
      color: root.bar ? root.bar.barForeground : Color.foreground
      font.family: root.bar ? root.bar.fontFamily : Style.font.family
      font.pixelSize: Style.font.body
      renderType: Text.NativeRendering
      opacity: root.service && root.service.connected ? 1.0 : 0.45
    }

    Text {
      id: icon
      anchors.baseline: number.baseline
      anchors.right: number.left
      anchors.rightMargin: Style.space(6)
      text: root.glyph
      color: number.color
      font.family: number.font.family
      font.pixelSize: Style.font.body + 2
      renderType: Text.NativeRendering
      opacity: number.opacity
    }

    // Postęp do celu, pod liczbą. Ścieżka bierze kolor stąd, co ścieżki suwaków
    // w panelach Omarchy, więc chodzi za motywem zamiast być na sztywno czarna.
    Rectangle {
      anchors.horizontalCenter: number.horizontalCenter
      // Do dołu pigułki, nie pod sam tekst: pod tekstem wychodził poza widget
      // i bar go ucinał.
      anchors.bottom: parent.bottom
      anchors.bottomMargin: Style.space(4)
      width: Math.round(number.implicitWidth)
      height: Style.space(2)
      radius: height / 2
      color: root.bar ? Style.selectedFillFor(root.bar.barForeground, Color.accent)
                      : Style.selectedFill

      Rectangle {
        anchors.left: parent.left
        width: Math.round(parent.width * root.progress)
        height: parent.height
        radius: parent.radius
        color: root.progress >= 1 ? (root.bar ? root.bar.urgent : Color.urgent)
                                  : (root.bar ? root.bar.barForeground : Color.foreground)
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
