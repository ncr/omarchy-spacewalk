import QtQuick
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Pigułka na barze: cienki pasek postępu do celu, a pod nim chodzik i kroki
// dnia. Klik otwiera panel; klik środkowym startuje albo zatrzymuje taśmę.
BarWidget {
  id: root
  moduleName: "io.github.ncr.spacewalk"

  readonly property var service: bar && bar.shell ? bar.shell.serviceFor("io.github.ncr.spacewalk") : null
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

  // Szerokość kreski, którą bar rysuje pod widgetem z otwartym panelem. Bez tej
  // podpowiedzi bar bierze 55% szerokości slotu (Bar.qml:1575) i wychodzi krótki
  // kikut; oficjalne widgety podają tu szerokość swojej treści, tak jak zegar.
  readonly property real openPanelIndicatorWidth: button.contentWidth

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
    // Chodzik z liczbą, bez marginesów — tyle mierzy pasek postępu i tyle samo
    // kreska otwartego panelu.
    readonly property real contentWidth: icon.implicitWidth + Style.space(6) + number.implicitWidth

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
      // Ten sam rozmiar co cyfry: chodzik ma mieścić się w wysokości czcionki,
      // a nie wystawać ponad wiersz.
      font.family: number.font.family
      font.pixelSize: Style.font.body
      renderType: Text.NativeRendering
      opacity: number.opacity
    }

    // Postęp do celu, nad chodzikiem i liczbą, na szerokość obu. Ścieżka bierze
    // kolor stąd, co ścieżki suwaków w panelach Omarchy, więc chodzi za motywem
    // zamiast być na sztywno czarna.
    Rectangle {
      anchors.horizontalCenter: parent.horizontalCenter
      anchors.top: parent.top
      anchors.topMargin: Style.space(2)
      width: Math.round(button.contentWidth)
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
