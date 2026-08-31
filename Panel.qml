import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "ncr.treadmill"
  ipcTarget: "ncr.treadmill"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var service: null
  property bool openedFromHotkey: false

  readonly property var barIdentity: hostWidget || root
  readonly property int goal: service ? service.dailyGoal : 10000
  readonly property int steps: service ? service.daySteps : 0
  readonly property real progress: Model.progress(steps, goal)
  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property string family: bar ? bar.fontFamily : Style.font.family

  // Tempo z ostatniej minuty; gdy taśma stoi, prognoza dla ustawionej prędkości.
  readonly property real stepsPerMinute: {
    if (!service) return 0
    var live = Model.paceFromSamples(service.paceOld, service.paceNew)
    if (live > 0) return live
    return Model.paceFromSpeed(service.speed > 0 ? service.speed : service.startSpeed,
                               service.strideMeters)
  }

  property var clockNow: new Date()
  Timer {
    running: root.opened
    interval: 10000
    repeat: true
    triggeredOnStart: true
    onTriggered: root.clockNow = new Date()
  }

  readonly property string caption: Model.goalCaption(steps, goal, stepsPerMinute, clockNow)

  readonly property string stateLabel: {
    if (!service) return "brak serwisu"
    switch (service.linkState) {
      case "connected": return service.walking ? "idzie" : "połączona, stoi"
      case "connecting": return "łączę..."
      case "scanning": return "szukam bieżni..."
      case "not_found": return "nie znalazłem bieżni"
      case "disconnected": return "rozłączona"
      default: return service.linkState
    }
  }

  function open() {
    openedFromHotkey = false
    setCenterHoverRevealSuppressed(false)
    root.controller.show()
  }

  function openFromHotkey() {
    openedFromHotkey = true
    root.controller.show()
    Qt.callLater(function() { if (root.opened) setCenterHoverRevealSuppressed(true) })
  }

  function close() {
    setCenterHoverRevealSuppressed(false)
    root.controller.hide()
  }

  function toggle() { root.opened ? root.close() : root.openFromHotkey() }

  function switchPanel(direction) {
    if (root.bar && typeof root.bar.switchPanelFrom === "function")
      root.bar.switchPanelFrom(root.barIdentity, direction)
  }

  function setCenterHoverRevealSuppressed(value) {
    if (root.bar && "centerHoverRevealSuppressed" in root.bar)
      root.bar.centerHoverRevealSuppressed = value
  }

  // Gdy taśma jedzie, pokazujemy jej odczyt; gdy stoi — to, co zostanie zadane
  // po starcie. Stojąca bieżnia raportuje zera i nie przyjmuje komend, więc
  // odczyt byłby mylący.
  readonly property real shownSpeed: service ? (service.walking ? service.speed : service.targetSpeed) : 0
  readonly property real shownIncline: service ? (service.walking ? service.incline : service.targetIncline) : 0

  function bumpSpeed(delta) {
    if (!service) return
    // Bieżnia obsługuje 1,0–6,0 km/h co 0,1 (jej własna deklaracja).
    service.setSpeed(Math.max(1.0, Math.min(6.0, shownSpeed + delta)))
  }

  function bumpIncline(delta) {
    if (!service) return
    // Nachylenie 0–9 co 1.
    service.setIncline(Math.max(0, Math.min(9, Math.round(shownIncline + delta))))
  }

  KeyboardPanel {
    id: panel
    anchorItem: root.anchorItem
    owner: root.barIdentity
    bar: root.bar
    open: root.opened
    centerOnBar: true
    focusTarget: keyCatcher
    contentWidth: panel.fittedContentWidth(Style.space(360))
    contentHeight: panel.fittedContentHeight(column.implicitHeight)

    PanelKeyCatcher {
      id: keyCatcher
      anchors.fill: parent
      onCloseRequested: root.close()
      onTabRequested: function(direction) { root.switchPanel(direction) }

      Column {
        id: column
        width: parent.width
        spacing: Style.space(14)
        topPadding: Style.space(16)
        bottomPadding: Style.space(16)

        // ---- kroki: główna liczba
        Column {
          width: parent.width
          spacing: Style.space(2)

          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: Model.formatSteps(root.steps)
            color: root.fg
            font.family: root.family
            font.pixelSize: 52
            font.bold: true
          }

          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: "kroków z " + Model.formatSteps(root.goal)
            color: root.fg
            opacity: 0.6
            font.family: root.family
            font.pixelSize: Style.font.body
          }
        }

        // ---- pasek postępu + kiedy koniec
        Column {
          width: parent.width
          spacing: Style.space(6)

          Rectangle {
            x: Style.space(16)
            width: parent.width - Style.space(32)
            height: Style.space(8)
            radius: height / 2
            color: Qt.rgba(1, 1, 1, 0.15)

            Rectangle {
              width: parent.width * root.progress
              height: parent.height
              radius: parent.radius
              color: root.progress >= 1 ? (root.bar ? root.bar.urgent : Color.urgent) : root.fg
              Behavior on width { NumberAnimation { duration: 250; easing.type: Easing.OutCubic } }
            }
          }

          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            text: root.caption
            color: root.fg
            opacity: 0.7
            font.family: root.family
            font.pixelSize: Style.font.bodySmall
          }
        }

        // ---- kalorie, czas, dystans
        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(28)

          Repeater {
            model: [
              { label: "kalorie", value: (root.service ? root.service.dayKcal : 0) + " kcal" },
              { label: "czas", value: Model.formatDuration(root.service ? root.service.dayElapsedS : 0) },
              { label: "dystans", value: Model.formatDistance(root.service ? root.service.dayDistanceM : 0) }
            ]
            Column {
              required property var modelData
              spacing: Style.space(2)
              Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: modelData.value
                color: root.fg
                font.family: root.family
                font.pixelSize: Style.font.subtitle
              }
              Text {
                anchors.horizontalCenter: parent.horizontalCenter
                text: modelData.label
                color: root.fg
                opacity: 0.55
                font.family: root.family
                font.pixelSize: Style.font.caption
              }
            }
          }
        }

        PanelSeparator { width: parent.width }

        // ---- prędkość
        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(12)

          PanelActionButton {
            iconText: "−"
            tooltipText: "wolniej o 0,5 km/h"
            foreground: root.fg
            enabled: root.service !== null
            onClicked: root.bumpSpeed(-0.5)
          }

          Column {
            spacing: Style.space(2)
            Text {
              anchors.horizontalCenter: parent.horizontalCenter
              text: root.shownSpeed.toFixed(1).replace(".", ",") + " km/h"
              color: root.fg
              font.family: root.family
              font.pixelSize: Style.font.title
            }
            Text {
              anchors.horizontalCenter: parent.horizontalCenter
              text: root.service && root.service.walking ? "prędkość" : "prędkość po starcie"
              color: root.fg
              opacity: 0.55
              font.family: root.family
              font.pixelSize: Style.font.caption
            }
          }

          PanelActionButton {
            iconText: "+"
            tooltipText: "szybciej o 0,5 km/h"
            foreground: root.fg
            enabled: root.service !== null
            onClicked: root.bumpSpeed(0.5)
          }
        }

        // ---- nachylenie
        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(12)

          PanelActionButton {
            iconText: "−"
            tooltipText: "nachylenie w dół"
            foreground: root.fg
            enabled: root.service !== null
            onClicked: root.bumpIncline(-1)
          }

          Column {
            spacing: Style.space(2)
            Text {
              anchors.horizontalCenter: parent.horizontalCenter
              text: String(Math.round(root.shownIncline))
              color: root.fg
              font.family: root.family
              font.pixelSize: Style.font.title
            }
            Text {
              anchors.horizontalCenter: parent.horizontalCenter
              text: root.service && root.service.walking ? "nachylenie" : "nachylenie po starcie"
              color: root.fg
              opacity: 0.55
              font.family: root.family
              font.pixelSize: Style.font.caption
            }
          }

          PanelActionButton {
            iconText: "+"
            tooltipText: "nachylenie w górę"
            foreground: root.fg
            enabled: root.service !== null
            onClicked: root.bumpIncline(1)
          }
        }

        // ---- start / stop
        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(10)

          Button {
            text: root.service && root.service.walking ? "Zatrzymaj" : "Start"
            enabled: root.service && root.service.connected
            onClicked: {
              if (!root.service) return
              if (root.service.walking) root.service.stop()
              else root.service.start()
            }
          }

          Button {
            text: "Pauza"
            enabled: root.service && root.service.walking
            onClicked: if (root.service) root.service.pause()
          }
        }

        // ---- stan połączenia
        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          text: root.stateLabel + (root.service && root.service.lastError !== ""
                                   ? " — " + root.service.lastError : "")
          color: root.fg
          opacity: 0.5
          font.family: root.family
          font.pixelSize: Style.font.caption
          width: parent.width - Style.space(32)
          horizontalAlignment: Text.AlignHCenter
          wrapMode: Text.WordWrap
        }
      }
    }
  }
}
