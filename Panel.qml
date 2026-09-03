import QtQuick
import Quickshell
import Quickshell.Io
import qs.Commons
import qs.Ui
import "Model.js" as Model

Panel {
  id: root
  moduleName: "io.github.ncr.spacewalk"
  ipcTarget: "io.github.ncr.spacewalk"
  manageIpc: false

  property var anchorItem: null
  property var hostWidget: null
  property var service: null
  property bool openedFromHotkey: false

  readonly property var barIdentity: hostWidget || root
  readonly property int goal: service ? service.dailyGoal : 10000

  // The cell under the cursor swaps the numbers up top to that day; leaving the
  // grid goes back to today. No clicking — peeking at history is a mouse motion,
  // not a choice you would have to undo.
  readonly property string selectedDay: hoveredDay ? hoveredDay.key : ""
  readonly property string todayKey: service && service.today !== "" ? service.today : Model.dayKey(new Date())
  readonly property bool showingToday: selectedDay === "" || selectedDay === todayKey
  readonly property var selectedRecord: {
    if (showingToday || !service || !service.history) return null
    return service.history[selectedDay] || { steps: 0, distance_m: 0, kcal: 0, elapsed_s: 0 }
  }

  readonly property int steps: selectedRecord ? selectedRecord.steps : (service ? service.daySteps : 0)
  readonly property int shownKcal: selectedRecord ? selectedRecord.kcal : (service ? service.dayKcal : 0)
  readonly property int shownElapsed: selectedRecord ? selectedRecord.elapsed_s : (service ? service.dayElapsedS : 0)
  readonly property int shownDistance: selectedRecord ? selectedRecord.distance_m : (service ? service.dayDistanceM : 0)
  readonly property real progress: Model.progress(steps, goal)
  readonly property color fg: bar ? bar.foreground : Color.foreground
  readonly property string family: bar ? bar.fontFamily : Style.font.family

  // Pace from the last minute; with the belt stopped, a forecast for the set speed.
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

  // The same line for today and for the previewed day — hiding it on a grid
  // cell click shortened the panel and everything below it jumped.
  readonly property string caption: showingToday
    ? Model.goalCaption(steps, goal, stepsPerMinute, clockNow)
    : Model.pastDayCaption(steps, goal)

  // Trouble is described matter-of-factly; only when all is well does the
  // carousel run in this line (following omaphones).
  readonly property string problemLabel: {
    if (!service) return "no service"
    switch (service.linkState) {
      case "connecting": return "connecting..."
      case "scanning": return "looking for the treadmill..."
      case "not_found": return "treadmill out of reach — flip its power switch"
      case "disconnected": return "disconnected"
      case "connected": return ""
      default: return service.linkState
    }
  }

  // Header subtitle: trouble is described matter-of-factly, and when all is
  // well a carousel of phrases runs here — one set for a moving belt, another
  // for a standing one. Speed and incline sit below in the tiles anyway.
  readonly property var walkingPhrases: [
    "You are walking",
    "Legs doing the work",
    "The desk sits, you do not",
    "Step by step to 10k",
    "Belt under control",
    "Legs earning the chair"
  ]

  readonly property var pausedPhrases: [
    "Stepped off the belt",
    "The belt is waiting",
    "Counter on hold",
    "Short break, right?"
  ]

  readonly property var idlePhrases: [
    "Treadmill ready",
    "Waiting for the switch",
    "Zero steps will not grow",
    "Incline set, your move"
  ]

  // The header subtitle goes uppercase with letter spacing and elides the
  // overflow, so the phrases have to be measured, not sized by eyeballing
  // character counts: what fits in one theme no longer fits in another.
  TextMetrics {
    id: metaMetrics
    font.family: root.family
    font.pixelSize: Style.font.caption
    font.bold: true
    font.letterSpacing: 1.2
  }

  // How much room the subtitle gets: header width minus the icon, the gaps,
  // and the switch at the right edge.
  readonly property real metaSpace: hero.width - hero.trailingInset - Style.font.display - Style.space(20)

  function fitsInHeader(text) {
    metaMetrics.text = String(text).toUpperCase()
    return metaMetrics.width <= metaSpace
  }

  function fitting(list) {
    var out = []
    for (var i = 0; i < list.length; i++) if (fitsInHeader(list[i])) out.push(list[i])
    return out.length > 0 ? out : [list[0]]
  }

  // Which phrase set is in force. Separate from the list itself, because
  // measuring text mutates a TextMetrics property — in a binding that would loop.
  readonly property string phraseSet: {
    if (!service || problemLabel !== "") return "none"
    if (service.walking) return "walk"
    return service.paused ? "pause" : "idle"
  }

  property var phrases: []

  function refreshPhrases() {
    if (phraseSet === "none") { phrases = []; return }
    if (phraseSet === "walk") phrases = fitting(walkingPhrases)
    else if (phraseSet === "pause") phrases = fitting(pausedPhrases)
    else phrases = fitting(idlePhrases)
    phraseIndex = 0
  }

  onPhraseSetChanged: refreshPhrases()
  onMetaSpaceChanged: refreshPhrases()
  Component.onCompleted: refreshPhrases()

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
    PropertyAnimation {
      target: hero; property: "metaOpacity"
      to: 0.0; duration: 180; easing.type: Easing.OutQuad
    }
    ScriptAction { script: root.phraseIndex = root.phraseIndex + 1 }
    PropertyAnimation {
      target: hero; property: "metaOpacity"
      to: 1.0; duration: 220; easing.type: Easing.InQuad
    }
  }

  // An animation cut off midway would leave the phrase half faded out.
  onRotatingChanged: if (!rotating) { phraseSwap.stop(); hero.metaOpacity = 1.0 }

  readonly property int gridWeeks: 13
  readonly property var gridModel: service && opened
    ? Model.gridDays(service.history, new Date(), gridWeeks) : []
  readonly property bool hasHistory: service && service.history
    ? Object.keys(service.history).length > 0 : false
  readonly property var dayAverage: service ? Model.averageSteps(service.history)
                                            : ({ steps: 0, days: 0 })

  property var hoveredDay: null
  // Only the day under the cursor. The average sits below the grid and repeating
  // it here showed the same number twice. The header row takes its height from
  // the label on the left, so an empty caption collapses nothing.
  readonly property string hoveredLabel: hoveredDay ? Model.formatDay(hoveredDay.date) : ""

  // Grid colors from the theme: four fill levels derived from the text color,
  // and a day that reached the goal gets the accent, to stand apart from the rest.
  function levelColor(level) {
    var base = bar ? bar.foreground : Color.foreground
    switch (level) {
      case 0: return Util.alpha(base, 0.10)
      case 1: return Util.alpha(base, 0.28)
      case 2: return Util.alpha(base, 0.48)
      case 3: return Util.alpha(base, 0.70)
      default: return Color.accent
    }
  }

  // The switch in the header replaced the button at the bottom: it starts the
  // belt and pauses it, so flipping it back resumes at the set speed and
  // incline instead of ending the workout. A full stop stays on the bar
  // widget's middle click.
  function toggleBelt() {
    if (!service) return
    if (service.walking) service.pause()
    else service.start()
  }

  readonly property bool beltBusy: service
    && ["sending", "control", "starting", "unconfirmed", "spinup", "setting"].indexOf(service.phaseName) !== -1

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

  // The tiles show the TARGET value, not the momentary reading. The arrows
  // change exactly that, and the treadmill speeds up and brakes along the way:
  // stepping off the belt you saw 1 km/h mid-braking though the target was 2.5.
  readonly property real shownSpeed: service ? service.targetSpeed : 0
  readonly property real shownIncline: service ? service.targetIncline : 0

  function bumpSpeed(delta) {
    if (!service) return
    // The treadmill supports 1.0–6.0 km/h in 0.1 steps (its own declaration).
    service.setSpeed(Math.max(1.0, Math.min(6.0, shownSpeed + delta)))
  }

  function bumpIncline(delta) {
    if (!service) return
    // Incline 0–9 in steps of 1.
    service.setIncline(Math.max(0, Math.min(9, Math.round(shownIncline + delta))))
  }

  // Where the panel card lies on screen — for tools/hero-set, which crops the
  // screenshots: the panel layer covers the whole screen, so the card rectangle
  // cannot be seen from outside. Published while the panel is open, empty when
  // closed.
  readonly property string panelRectText: panel.open
    ? [Math.round(panel.cardOrigin.x), Math.round(panel.cardOrigin.y),
       Math.round(panel.contentWidth), Math.round(panel.contentHeight)].join(" ")
    : ""
  onPanelRectTextChanged: if (service) service.panelRect = panelRectText

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

        // ---- header: what the treadmill is doing, and the switch that runs it
        Item {
          id: header
          width: parent.width - Style.space(32)
          x: Style.space(16)
          implicitHeight: hero.implicitHeight

          PanelHero {
            id: hero
            width: parent.width
            title: "Spacewalk 3S"
            meta: root.heroMeta
            foreground: root.fg
            fontFamily: root.family
            iconOpacity: root.service && root.service.connected ? 1.0 : 0.5

            iconComponent: Component {
              Text {
                text: "󰖃"
                color: root.fg
                font.family: root.family
                font.pixelSize: Style.font.display
              }
            }

            // Two positions instead of a button at the bottom: the belt runs or stands.
            trailingControl: Component {
              ToggleSwitch {
                id: beltSwitch
                checked: root.service ? root.service.walking : false
                busy: root.beltBusy
                interactive: root.service && root.service.connected
                foreground: root.fg
                onToggled: root.toggleBelt()

                PanelToolTip {
                  visible: beltSwitch.containsMouse
                  text: root.service && root.service.walking
                        ? "pauses the belt; flip again to resume"
                        : (root.service && root.service.paused
                           ? "resumes at the set speed and incline"
                           : "starts at the set speed and incline")
                  fontFamily: root.family
                }
              }
            }
          }
        }

        // ---- steps: the main number
        //
        // Full width with centering inside it: with plain centering the label
        // changed width along with the number and twitched while moving the
        // cursor across the grid — and here it changes with every cell.
        Text {
          width: parent.width
          height: Math.round(52 * 1.25)
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
          text: Model.formatSteps(root.steps)
          color: root.fg
          font.family: root.family
          font.pixelSize: 52
          font.bold: true
        }

        // ---- progress bar + when it ends
        Column {
          width: parent.width
          spacing: Style.space(6)

          Rectangle {
            x: Style.space(16)
            width: parent.width - Style.space(32)
            height: Style.space(8)
            radius: height / 2
            // Track from the theme, like the sliders in Omarchy panels.
            color: root.bar ? Style.selectedFillFor(root.bar.foreground, Color.accent)
                            : Style.selectedFill

            Rectangle {
              width: parent.width * root.progress
              height: parent.height
              radius: parent.radius
              color: root.progress >= 1 ? (root.bar ? root.bar.urgent : Color.urgent) : root.fg
              // Short, because while moving the cursor across the grid the bar
              // gets a new value every few tens of milliseconds and a longer
              // animation turns into floating.
              Behavior on width { NumberAnimation { duration: 110; easing.type: Easing.OutCubic } }
            }
          }

          Text {
            width: parent.width
            height: Math.round(Style.font.bodySmall * 1.6)
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: root.caption
            color: root.fg
            opacity: 0.7
            font.family: root.family
            font.pixelSize: Style.font.bodySmall
          }
        }

        // ---- calories, time, distance
        // Three equal columns instead of a content-sized row: otherwise every
        // change in digit count shifts all three sideways.
        Row {
          id: statsRow
          width: parent.width
          spacing: Style.space(28)
          height: Math.round(Style.font.subtitle * 1.5 + Style.font.caption * 1.7)

          readonly property real cellWidth:
            Math.max(0, (width - spacing * 2) / 3)

          Repeater {
            model: [
              { label: "calories", value: root.shownKcal + " kcal" },
              { label: "time", value: Model.formatDuration(root.shownElapsed) },
              { label: "distance", value: Model.formatDistance(root.shownDistance) }
            ]
            Column {
              required property var modelData
              width: statsRow.cellWidth
              spacing: Style.space(2)
              Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: modelData.value
                color: root.fg
                font.family: root.family
                font.pixelSize: Style.font.subtitle
              }
              Text {
                width: parent.width
                horizontalAlignment: Text.AlignHCenter
                elide: Text.ElideRight
                text: modelData.label
                color: root.fg
                opacity: 0.55
                font.family: root.family
                font.pixelSize: Style.font.caption
                font.capitalization: Font.AllUppercase
                font.letterSpacing: 0.4
              }
            }
          }
        }


        PanelSeparator { width: parent.width }

        // ---- grid of the last 13 weeks
        Column {
          width: parent.width
          spacing: Style.space(6)

          // Above the grid only the date of the day under the cursor, centered.
          // The row keeps its height even when empty, so the grid does not jump.
          Text {
            width: parent.width
            height: Math.round(Style.font.caption * 1.7)
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: root.hoveredLabel
            color: root.fg
            opacity: 0.75
            font.family: root.family
            font.pixelSize: Style.font.caption
          }

          Grid {
            id: dayGrid
            anchors.horizontalCenter: parent.horizontalCenter

            // Guard over the whole grid area: when the cursor leaves it, we go
            // back to today. A cell's own "I left" is not enough — on a fast move
            // the event can fail to arrive and the last previewed day sticks.
            HoverHandler {
              id: gridHover
              onHoveredChanged: if (!hovered) root.hoveredDay = null
            }
            rows: 7
            columns: root.gridWeeks
            flow: Grid.TopToBottom
            spacing: Style.space(3)

            Repeater {
              model: root.gridModel

              Rectangle {
                required property var modelData
                width: Style.space(13)
                height: width
                radius: Style.space(3)
                opacity: modelData.future ? 0.25 : 1.0
                color: root.levelColor(Model.dayLevel(modelData.steps, root.goal))
                // The selected day outlined in the text color, today in the
                // urgent color; selection matters more — it governs the numbers.
                border.width: modelData.key === root.selectedDay ? 2
                              : (modelData.key === root.todayKey ? 1 : 0)
                border.color: modelData.key === root.selectedDay
                              ? root.fg
                              : (root.bar ? root.bar.urgent : Color.urgent)

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  onEntered: root.hoveredDay = modelData
                  // Only its own exit: when crossing between cells the signals
                  // interleave, and clearing blindly would wipe the day that just
                  // came under the cursor.
                  onExited: if (root.hoveredDay === modelData) root.hoveredDay = null
                }
              }
            }
          }

          // Average over walking days — one number that sums up the grid.
          Text {
            width: parent.width
            height: Math.round(Style.font.bodySmall * 1.6)
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            visible: root.hasHistory
            text: "You average " + Model.formatSteps(root.dayAverage.steps) + " steps a day"
            color: root.fg
            opacity: 0.55
            font.family: root.family
            font.pixelSize: Style.font.bodySmall
          }

          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: !root.hasHistory
            text: "history starts with your first walk"
            color: root.fg
            opacity: 0.5
            font.family: root.family
            font.pixelSize: Style.font.caption
          }
        }

        PanelSeparator { width: parent.width }

        // ---- controls: two tiles, arrows next to the value
        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(10)

          Repeater {
            model: [
              // Fixed labels: "speed after start" did not fit in the tile and
              // stretched both. That the value is still waiting for a start shows
              // in the dimming and in the tooltip.
              { kind: "speed", label: "speed",
                value: root.shownSpeed.toFixed(1) + " km/h" },
              { kind: "incline", label: "incline",
                // The treadmill reports incline in percent (0–9%), so the
                // percent sign belongs to the value, not the label.
                value: String(Math.round(root.shownIncline)) + "%" }
            ]

            Rectangle {
              required property var modelData
              width: Math.round((column.width - Style.space(42)) / 2)
              height: tileRow.implicitHeight + Style.space(10)
              radius: Style.space(8)
              color: Util.alpha(root.fg, 0.07)

              Row {
                id: tileRow
                anchors.centerIn: parent
                spacing: Style.space(4)

                PanelActionButton {
                  anchors.verticalCenter: parent.verticalCenter
                  iconText: "−"
                  tooltipText: (modelData.kind === "speed" ? "0.5 km/h slower" : "lower the incline")
                               + (root.service && root.service.walking ? "" : " — set once it starts")
                  foreground: root.fg
                  enabled: root.service !== null
                  onClicked: modelData.kind === "speed" ? root.bumpSpeed(-0.5) : root.bumpIncline(-1)
                }

                Column {
                  anchors.verticalCenter: parent.verticalCenter
                  spacing: Style.space(1)

                  Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: modelData.value
                    color: root.fg
                    opacity: root.service && root.service.walking ? 1.0 : 0.7
                    font.family: root.family
                    font.pixelSize: Style.font.subtitle
                  }

                  Text {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: modelData.label
                    color: root.fg
                    opacity: 0.5
                    font.family: root.family
                    font.pixelSize: Style.font.caption
                    font.capitalization: Font.AllUppercase
                    font.letterSpacing: 0.4
                    elide: Text.ElideRight
                    width: Math.min(implicitWidth, tileRow.parent.width - Style.space(56))
                    horizontalAlignment: Text.AlignHCenter
                  }
                }

                PanelActionButton {
                  anchors.verticalCenter: parent.verticalCenter
                  iconText: "+"
                  tooltipText: (modelData.kind === "speed" ? "0.5 km/h faster" : "raise the incline")
                               + (root.service && root.service.walking ? "" : " — set once it starts")
                  foreground: root.fg
                  enabled: root.service !== null
                  onClicked: modelData.kind === "speed" ? root.bumpSpeed(0.5) : root.bumpIncline(1)
                }
              }
            }
          }
        }

      }
    }
  }
}
