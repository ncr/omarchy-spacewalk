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

  // Kratka pod kursorem podmienia liczby u góry na tamten dzień; zjazd z kratek
  // wraca do dzisiaj. Bez klikania — podglądanie historii to ruch myszy, nie
  // wybór, który trzeba potem cofać.
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

  // Ta sama linijka dla dziś i dla podglądanego dnia — schowanie jej przy
  // kliknięciu w kratkę skracało panel i wszystko pod spodem podskakiwało.
  readonly property string caption: showingToday
    ? Model.goalCaption(steps, goal, stepsPerMinute, clockNow)
    : Model.pastDayCaption(steps, goal)

  // Kłopoty opisujemy rzeczowo; dopiero gdy wszystko gra, w tej linii chodzi
  // karuzela (wzorem omaphones).
  readonly property string problemLabel: {
    if (!service) return "brak serwisu"
    switch (service.linkState) {
      case "connecting": return "łączę..."
      case "scanning": return "szukam bieżni..."
      case "not_found": return "bieżnia nieosiągalna — pstryknij wyłącznikiem"
      case "disconnected": return "rozłączona"
      case "connected": return ""
      default: return service.linkState
    }
  }

  readonly property var walkingPhrases: [
    "Idziesz.",
    "Nogi robią swoje",
    "Biurko stoi, ty nie",
    "Krok po kroku do dziesiątki",
    "Taśma pod kontrolą",
    "Dziś nogi zarabiają na siedzenie"
  ]

  readonly property var pausedPhrases: [
    "Spauzowana — zszedłeś z taśmy",
    "Taśma czeka",
    "Wróć, licznik stoi",
    "Przerwa. Krótka, prawda?"
  ]

  readonly property var idlePhrases: [
    "Bieżnia gotowa",
    "Taśma czeka na Start",
    "Zero kroków samo nie urośnie",
    "Nachylenie ustawione, reszta należy do Ciebie"
  ]

  readonly property var phrases: {
    if (!service || problemLabel !== "") return []
    if (service.walking) return walkingPhrases
    return service.paused ? pausedPhrases : idlePhrases
  }

  readonly property int gridWeeks: 13
  readonly property var gridModel: service && opened
    ? Model.gridDays(service.history, new Date(), gridWeeks) : []
  readonly property bool hasHistory: service && service.history
    ? Object.keys(service.history).length > 0 : false
  readonly property var dayAverage: service ? Model.averageSteps(service.history)
                                            : ({ steps: 0, days: 0 })

  property var hoveredDay: null
  // Tylko dzień pod kursorem. Średnia stoi pod kratką i powtarzanie jej tutaj
  // pokazywało tę samą liczbę dwa razy. Wiersz nagłówka bierze wysokość z
  // napisu po lewej, więc pusty podpis niczego nie zwija.
  readonly property string hoveredLabel: hoveredDay ? Model.formatDay(hoveredDay.date) : ""

  // Kolory kratki z motywu: cztery stopnie wypełnienia liczone od koloru tekstu,
  // a dzień z osiągniętym celem dostaje akcent, żeby odcinał się od reszty.
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

  property int phraseIndex: 0
  readonly property bool rotating: opened && phrases.length > 1
  readonly property string stateLabel: problemLabel !== ""
    ? problemLabel
    : (phrases.length > 0 ? phrases[phraseIndex % phrases.length] : "")

  // Nowy zestaw fraz zaczyna się od pierwszej, żeby zmiana stanu od razu mówiła,
  // co się stało, zamiast wpadać w środek poprzedniej karuzeli.
  onPhrasesChanged: phraseIndex = 0

  Timer {
    interval: 2800
    running: root.rotating
    repeat: true
    onTriggered: phraseSwap.restart()
  }

  SequentialAnimation {
    id: phraseSwap
    PropertyAnimation {
      target: stateText; property: "opacity"
      to: 0.0; duration: 180; easing.type: Easing.OutQuad
    }
    ScriptAction { script: root.phraseIndex = root.phraseIndex + 1 }
    PropertyAnimation {
      target: stateText; property: "opacity"
      to: 0.55; duration: 220; easing.type: Easing.InQuad
    }
  }

  // Tylko Start i Zatrzymaj. Bieżnia sama wstrzymuje taśmę, gdy z niej zejdziesz,
  // a Start ją wtedy wznawia — osobny przycisk pauzy niczego nie dokładał.
  readonly property string mainButtonLabel: service && service.walking ? "Zatrzymaj" : "Start"

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

          // Oba napisy dostają całą szerokość panelu i środkują się w niej same.
          // Przy zwykłym centrowaniu każdy z nich zmieniał szerokość razem
          // z treścią, więc przy przesuwaniu kursora po kratkach cały blok
          // drgał — a zmienia się tu co kratkę.
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

          Text {
            width: parent.width
            height: Math.round(Style.font.body * 1.6)
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            text: root.showingToday
                  ? "kroków z " + Model.formatSteps(root.goal)
                  : "kroków — " + Model.formatDay(Model.parseKey(root.selectedDay))
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
            // Ścieżka z motywu, jak przy suwakach w panelach Omarchy.
            color: root.bar ? Style.selectedFillFor(root.bar.foreground, Color.accent)
                            : Style.selectedFill

            Rectangle {
              width: parent.width * root.progress
              height: parent.height
              radius: parent.radius
              color: root.progress >= 1 ? (root.bar ? root.bar.urgent : Color.urgent) : root.fg
              // Krótko, bo przy przesuwaniu kursora po kratkach pasek dostaje
              // nową wartość co kilkadziesiąt milisekund i dłuższa animacja
              // zamienia się w pływanie.
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

        // ---- kalorie, czas, dystans
        // Trzy równe kolumny zamiast wiersza dopasowanego do treści: inaczej
        // każda zmiana liczby cyfr przesuwa wszystkie trzy w bok.
        Row {
          id: statsRow
          width: parent.width
          spacing: Style.space(28)
          height: Math.round(Style.font.subtitle * 1.5 + Style.font.caption * 1.7)

          readonly property real cellWidth:
            Math.max(0, (width - spacing * 2) / 3)

          Repeater {
            model: [
              { label: "kalorie", value: root.shownKcal + " kcal" },
              { label: "czas", value: Model.formatDuration(root.shownElapsed) },
              { label: "dystans", value: Model.formatDistance(root.shownDistance) }
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

        // ---- kratka ostatnich 13 tygodni
        Column {
          width: parent.width
          spacing: Style.space(6)

          Item {
            width: parent.width - Style.space(32)
            x: Style.space(16)
            height: gridHead.implicitHeight

            Text {
              id: gridHead
              anchors.left: parent.left
              text: "ostatnie 13 tygodni"
              color: root.fg
              opacity: 0.55
              font.family: root.family
              font.pixelSize: Style.font.caption
            }

            Text {
              anchors.right: parent.right
              text: root.hoveredLabel
              color: root.fg
              opacity: 0.75
              font.family: root.family
              font.pixelSize: Style.font.caption
            }
          }

          Grid {
            id: dayGrid
            anchors.horizontalCenter: parent.horizontalCenter

            // Strażnik całego obszaru kratek: gdy kursor go opuszcza, wracamy
            // do dzisiaj. Samo „wyszedłem z kratki" nie wystarcza — przy szybkim
            // ruchu zdarzenie potrafi nie dojść i zostaje ostatni podglądany dzień.
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
                // Wybrany dzień obrysowany kolorem tekstu, dzisiejszy kolorem
                // alarmowym; wybór jest ważniejszy, bo to on rządzi liczbami.
                border.width: modelData.key === root.selectedDay ? 2
                              : (modelData.key === root.todayKey ? 1 : 0)
                border.color: modelData.key === root.selectedDay
                              ? root.fg
                              : (root.bar ? root.bar.urgent : Color.urgent)

                MouseArea {
                  anchors.fill: parent
                  hoverEnabled: true
                  onEntered: root.hoveredDay = modelData
                  // Tylko własne wyjście: przy przechodzeniu między kratkami
                  // sygnały się przeplatają i czyszczenie na ślepo gasiłoby
                  // dzień, który właśnie wszedł pod kursor.
                  onExited: if (root.hoveredDay === modelData) root.hoveredDay = null
                }
              }
            }
          }

          // Średnia dzienna z całego okresu — jedna liczba, która podsumowuje kratkę.
          Text {
            width: parent.width
            height: Math.round(Style.font.bodySmall * 1.6)
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            elide: Text.ElideRight
            visible: root.hasHistory
            text: Model.formatSteps(root.dayAverage.steps) + " — średnia dzienna"
            color: root.fg
            opacity: 0.55
            font.family: root.family
            font.pixelSize: Style.font.bodySmall
          }

          Text {
            anchors.horizontalCenter: parent.horizontalCenter
            visible: !root.hasHistory
            text: "historia buduje się od pierwszego marszu"
            color: root.fg
            opacity: 0.5
            font.family: root.family
            font.pixelSize: Style.font.caption
          }
        }

        PanelSeparator { width: parent.width }

        // ---- sterowanie: dwa kafelki, strzałki przy wartości
        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(10)

          Repeater {
            model: [
              // Podpisy stałe: „prędkość po starcie" nie mieściła się w kafelku
              // i rozpychała oba. Że wartość dopiero czeka na start, widać po
              // przygaszeniu i z podpowiedzi.
              { kind: "speed", label: "prędkość",
                value: root.shownSpeed.toFixed(1).replace(".", ",") + " km/h" },
              { kind: "incline", label: "nachylenie",
                value: String(Math.round(root.shownIncline)) }
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
                  tooltipText: (modelData.kind === "speed" ? "wolniej o 0,5 km/h" : "nachylenie w dół")
                               + (root.service && root.service.walking ? "" : " — zadam po starcie")
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
                  tooltipText: (modelData.kind === "speed" ? "szybciej o 0,5 km/h" : "nachylenie w górę")
                               + (root.service && root.service.walking ? "" : " — zadam po starcie")
                  foreground: root.fg
                  enabled: root.service !== null
                  onClicked: modelData.kind === "speed" ? root.bumpSpeed(0.5) : root.bumpIncline(1)
                }
              }
            }
          }
        }

        // ---- start / stop
        Row {
          anchors.horizontalCenter: parent.horizontalCenter
          spacing: Style.space(10)

          Button {
            text: root.mainButtonLabel
            enabled: root.service && root.service.connected
            tooltipText: root.service && root.service.walking
                         ? "zatrzymuje taśmę; licznik dnia zostaje"
                         : "rusza z ustawioną prędkością i nachyleniem"
            foreground: root.fg
            fontFamily: root.family
            bordered: true
            // Wyróżniony wypełnieniem — to on jest tym, po co się tu przychodzi.
            selected: true
            horizontalPadding: Style.spacing.controlPaddingX + Style.space(6)
            onClicked: {
              if (!root.service) return
              if (root.service.walking) root.service.stop()
              else root.service.start()   // start wznawia też taśmę wstrzymaną
            }
          }
        }

        // ---- co się właśnie dzieje ze startem
        //
        // Zawsze zajmuje swój wiersz, choćby pusty, i nigdy się nie zawija:
        // pojawianie się tej linijki i przeskakiwanie jej na dwie linie
        // zmieniało wysokość panelu, a panel wisi pod paskiem i rośnie w dół,
        // więc cała zawartość podskakiwała.
        Text {
          anchors.horizontalCenter: parent.horizontalCenter
          opacity: text === "" ? 0 : 0.8
          text: root.service ? root.service.phaseText : ""
          color: root.service && root.service.phaseName === "failed"
                 ? (root.bar ? root.bar.urgent : Color.urgent) : root.fg
          font.family: root.family
          font.pixelSize: Style.font.bodySmall
          width: parent.width - Style.space(32)
          height: Math.round(Style.font.bodySmall * 1.6)
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
          wrapMode: Text.NoWrap
          elide: Text.ElideRight
        }

        // ---- stan połączenia
        Text {
          id: stateText
          anchors.horizontalCenter: parent.horizontalCenter
          text: root.stateLabel + (root.service && root.service.lastError !== ""
                                   ? " — " + root.service.lastError : "")
          color: root.fg
          opacity: 0.5
          font.family: root.family
          font.pixelSize: Style.font.caption
          width: parent.width - Style.space(32)
          height: Math.round(Style.font.caption * 1.7)
          horizontalAlignment: Text.AlignHCenter
          verticalAlignment: Text.AlignVCenter
          wrapMode: Text.NoWrap
          elide: Text.ElideRight
        }
      }
    }
  }
}
