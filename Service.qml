import QtQuick
import Quickshell
import Quickshell.Io

// Trzyma most do bieżni przy życiu przez całą sesję, niezależnie od tego, czy
// panel jest otwarty. Shell montuje ten plik przy starcie (shell.qml:_syncServices)
// i wystawia go widgetowi przez shell.serviceFor("ncr.treadmill").
Item {
  id: root

  property var shell: null
  property var manifest: null

  // Ustawienia przychodzą z wpisu widgetu w shell.json — widget je tu wstrzykuje,
  // bo to on je dostaje od baru.
  property string address: ""
  property int dailyGoal: 10000
  property real startSpeed: 2.5
  property real startIncline: 3
  property real strideMeters: 0

  // Stan czytany przez widget i panel.
  // Nie „state": to wbudowana właściwość Item i własny mechanizm stanów Qt.
  property string linkState: "starting"  // starting | scanning | connecting | connected | disconnected | not_found
  property bool connected: linkState === "connected"
  property real speed: 0
  property real incline: 0
  // Co zostanie zadane po starcie. Stojąca bieżnia raportuje zera, więc bez
  // tego panel nie miałby czego pokazać.
  property real targetSpeed: 2.5
  property real targetIncline: 3
  property int daySteps: 0
  property int daySteps0: 0              // kroki dnia w chwili startu sesji — do tempa
  property int dayDistanceM: 0
  property int dayKcal: 0
  property int dayElapsedS: 0
  property int sessionElapsedS: 0
  property bool walking: false
  property string lastError: ""
  property int linesSeen: 0

  // Dwie próbki kroków ze znacznikiem czasu — tempo liczy się z ostatniej minuty,
  // nie ze średniej sesji, żeby po przerwie prognoza reagowała od razu.
  property var paceOld: null
  property var paceNew: null

  readonly property string scriptPath: {
    var dir = String(Qt.resolvedUrl("."))
    return dir.replace(/^file:\/\//, "") + "treadmill-bridge.py"
  }

  function applySettings(settings) {
    if (!settings) return
    var changedTransport = false
    if (settings.address !== undefined && settings.address !== null && settings.address !== address) {
      address = String(settings.address)
      changedTransport = true
    }
    if (settings.strideMeters !== undefined && settings.strideMeters !== null
        && Number(settings.strideMeters) !== strideMeters) {
      strideMeters = Number(settings.strideMeters)
      changedTransport = true
    }
    if (settings.dailyGoal !== undefined && settings.dailyGoal !== null)
      dailyGoal = Math.max(1, Math.round(Number(settings.dailyGoal)))
    if (settings.startSpeed !== undefined && settings.startSpeed !== null)
      startSpeed = Number(settings.startSpeed)
    if (settings.startIncline !== undefined && settings.startIncline !== null)
      startIncline = Number(settings.startIncline)
    if (changedTransport && bridge.running) restart()
  }

  function send(command) {
    if (!bridge.running) {
      lastError = "most nie działa"
      return
    }
    bridge.write(command + "\n")
  }

  // Most sam dosyła prędkość i nachylenie kilkanaście sekund po starcie —
  // bieżnia ignoruje cele zadane, zanim rozpędzi się do 1 km/h.
  function start() {
    send("start " + Number(startSpeed).toFixed(1) + " " + Math.round(startIncline))
  }

  function stop() { send("stop") }
  function pause() { send("pause") }
  function setSpeed(kmh) {
    targetSpeed = kmh          // natychmiast w panelu, nawet gdy taśma stoi
    send("speed " + Number(kmh).toFixed(1))
  }

  function setIncline(percent) {
    targetIncline = Math.round(percent)
    send("incline " + Math.round(percent))
  }

  function restart() {
    bridge.running = false
    bridge.running = true
  }

  function handleLine(line) {
    var text = String(line).trim()
    if (text === "") return
    linesSeen++
    var msg
    try {
      msg = JSON.parse(text)
    } catch (e) {
      lastError = text
      return
    }
    if (msg.t === "status") {
      linkState = msg.state
      if (msg.state !== "connected") walking = false
    } else if (msg.t === "error") {
      lastError = msg.msg || ""
    } else if (msg.t === "targets") {
      if (msg.target_speed !== null && msg.target_speed !== undefined) targetSpeed = msg.target_speed
      if (msg.target_incline !== null && msg.target_incline !== undefined) targetIncline = msg.target_incline
    } else if (msg.t === "data") {
      applyData(msg)
    }
  }

  function applyData(msg) {
    if (msg.speed !== undefined) {
      speed = msg.speed
      walking = msg.speed > 0.1
    }
    if (msg.incline !== undefined) incline = msg.incline
    if (msg.elapsed_s !== undefined) sessionElapsedS = msg.elapsed_s
    if (msg.day_steps !== undefined) {
      daySteps = msg.day_steps
      var sample = { time: Date.now(), steps: msg.day_steps }
      // Trzymamy próbkę sprzed ~60 s: nowa staje się starą dopiero po minucie.
      if (!paceNew) { paceNew = sample; paceOld = sample }
      else if (sample.time - paceNew.time >= 20000) { paceOld = paceNew; paceNew = sample }
      else paceNew = sample
    }
    if (msg.day_distance_m !== undefined) dayDistanceM = msg.day_distance_m
    if (msg.day_kcal !== undefined) dayKcal = msg.day_kcal
    if (msg.day_elapsed_s !== undefined) dayElapsedS = msg.day_elapsed_s
  }

  // Uruchamiany dopiero po zbudowaniu obiektu: przy `running: true` wpisanym
  // wprost proces rusza, zanim stdout dostanie swój SplitParser, i pierwsze
  // (a w praktyce wszystkie) linie przepadają.
  Component.onCompleted: bridge.running = true

  // Podgląd stanu z terminala: `omarchy-shell treadmill state`.
  // console.log z pluginu użytkownika nie trafia do dziennika systemowego,
  // więc to jedyny sposób, żeby zajrzeć serwisowi do środka na żywo.
  IpcHandler {
    target: "treadmill"

    function dump(): string {
      return JSON.stringify({
        linkState: root.linkState, linesSeen: root.linesSeen, speed: root.speed,
        incline: root.incline, targetSpeed: root.targetSpeed, targetIncline: root.targetIncline,
        walking: root.walking, daySteps: root.daySteps,
        dayKcal: root.dayKcal, dayElapsedS: root.dayElapsedS,
        dayDistanceM: root.dayDistanceM, lastError: root.lastError
      })
    }

    function start(): string { root.start(); return "ok" }
    function stop(): string { root.stop(); return "ok" }
    function speed(kmh: real): string { root.setSpeed(kmh); return "ok" }
    function incline(percent: real): string { root.setIncline(percent); return "ok" }
  }

  Process {
    id: bridge
    stdinEnabled: true
    command: {
      var argv = ["uv", "run", "--script", root.scriptPath]
      if (root.address !== "") argv.push("--address", root.address)
      if (root.strideMeters > 0) argv.push("--stride", String(root.strideMeters))
      argv.push("--speed", String(root.startSpeed), "--incline", String(root.startIncline))
      return argv
    }
    stdout: SplitParser { onRead: function(line) { root.handleLine(line) } }
    stderr: SplitParser { onRead: function(line) { root.lastError = String(line) } }
    onExited: function(code) {
      root.linkState = "disconnected"
      root.walking = false
      // Most nie powinien kończyć pracy — sam wznawia połączenie. Jak jednak
      // padnie (brak uv, błąd składni), podnosimy go po chwili, nie w pętli.
      bridgeRestart.restart()
    }
  }

  Timer {
    id: bridgeRestart
    interval: 10000
    onTriggered: if (!bridge.running) bridge.running = true
  }
}
