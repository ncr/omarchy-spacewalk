import QtQuick
import qs.Commons
import qs.Ui
import "shared" as Shared
import "Model.js" as Model

// Walker and today's steps on the bar.
// Click opens the panel; middle click starts or stops the belt.
BarWidget {
  id: root
  moduleName: "io.github.ncr.spacewalk"

  readonly property var service: Shared.ServiceRegistry.service
  readonly property int goal: service ? service.dailyGoal : 10000
  readonly property int steps: service ? service.daySteps : 0
  // Right click flips the number between steps done and steps left to the goal.
  // Resets on a shell restart.
  property bool showRemaining: false
  readonly property int stepsRemaining: Math.max(0, goal - steps)
  // One fixed walker. A second glyph for while walking was dropped: this font
  // has no runner shape and it came out as an alien mark. What the treadmill is
  // doing shows in the panel.
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

  // Width of the line the bar draws under the widget whose panel is open. Without
  // this hint the bar takes 55% of the slot width (Bar.qml:1575) and a short stub
  // comes out; official widgets report their content width here, like the clock.
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

  // The number centers within the bar's full height — exactly like the labels of
  // neighboring widgets. The walker sits beside it, on ITS baseline: kept in one
  // string with the digits it lifted them a few pixels, because the nerd-font
  // glyph has different metrics than the digits and centering counted its height.
  Item {
    id: button
    // No anchors.fill: on the first paint the parent has no size yet, the widget
    // comes out zero, and the shell strikes such a widget from the bar layout.
    width: implicitWidth
    height: implicitHeight
    implicitWidth: icon.implicitWidth + Style.space(6) + number.implicitWidth + Style.space(17)
    implicitHeight: root.bar ? root.bar.barSize : Style.space(24)

    readonly property real glyphSlot: (icon.implicitWidth + Style.space(6)) / 2
    // Walker plus number, no margins — the width of the open-panel line.
    readonly property real contentWidth: icon.implicitWidth + Style.space(6) + number.implicitWidth

    Text {
      id: number
      anchors.centerIn: parent
      anchors.horizontalCenterOffset: button.glyphSlot
      // The bar holds no single line — the built-in clock sits a pixel below the
      // geometric center of the slot. We align to it: it sets the bar's rhythm.
      anchors.verticalCenterOffset: 1
      text: Model.formatSteps(root.showRemaining ? root.stepsRemaining : root.steps)
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
      // Same size as the digits: the walker is to fit within the font height,
      // not stick out above the line.
      font.family: number.font.family
      font.pixelSize: Style.font.body
      renderType: Text.NativeRendering
      opacity: number.opacity
    }

    MouseArea {
      anchors.fill: parent
      acceptedButtons: Qt.LeftButton | Qt.MiddleButton | Qt.RightButton
      hoverEnabled: true
      onClicked: function(mouse) {
        if (!root.service) return
        if (mouse.button === Qt.MiddleButton) {
          if (root.service.walking) root.service.stop()
          else root.service.start()
        } else if (mouse.button === Qt.RightButton) {
          root.showRemaining = !root.showRemaining
        } else {
          root.togglePanel()
        }
      }
    }
  }
}
