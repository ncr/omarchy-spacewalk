import QtQuick
import Quickshell
import Quickshell.Io

// Keeps the treadmill bridge alive for the whole session, regardless of whether
// the panel is open. The shell mounts this file at startup (shell.qml:_syncServices)
// and exposes it to the widget via shell.serviceFor("io.github.ncr.spacewalk").
Item {
  id: root

  property var shell: null
  property var manifest: null

  // Settings come from the widget's entry in shell.json — the widget injects
  // them here, because it is the one that gets them from the bar.
  property string address: ""
  property int dailyGoal: 10000
  property real startSpeed: 2.5
  property real startIncline: 3
  property real strideMeters: 0
  // Port on which the iPhone shortcut receives transitions. 0 (the default) means
  // the server does not start at all — it is enabled only by a settings entry.
  property int phonePort: 0

  // State read by the widget and the panel.
  // Not "state": that is a built-in Item property and Qt's own state mechanism.
  property string today: ""
  property string linkState: "starting"  // starting | scanning | connecting | connected | disconnected | not_found
  property bool connected: linkState === "connected"
  property real speed: 0
  property real incline: 0
  // What gets requested after start. A standing treadmill reports zeros, so
  // without this the panel would have nothing to show.
  property real targetSpeed: 2.5
  property real targetIncline: 3
  property int daySteps: 0
  property int daySteps0: 0              // day steps at session start — for pace
  property int dayDistanceM: 0
  property int dayKcal: 0
  property int dayElapsedS: 0
  property int sessionElapsedS: 0
  property bool walking: false
  // A command sent to the belt, not yet reflected in its readings. The panel
  // throws the switch knob to `intendedWalking` at once and pulses it until
  // the belt catches up, so a press never looks like it did nothing. The belt
  // takes a few seconds to spin up or coast to a stop, hence the watchdog.
  property bool commandPending: false
  property bool intendedWalking: false
  property string lastError: ""
  // Start progress, shown in the panel. The treadmill starts with a delay and
  // accepts targets only once up to speed, so without this Start looks dead.
  property string phaseName: ""
  property string phaseText: ""
  // running | paused | stopped. Paused means you stepped off the belt and can
  // resume; stopped, that the treadmill halted on command or via the switch.
  property string beltState: "stopped"
  // Totals from recent days: {"2026-09-01": {steps, distance_m, kcal, elapsed_s}}.
  // The bridge reads the directory once at startup, so the grid does not hit
  // the disk every time the panel opens.
  property var history: ({})
  readonly property bool paused: beltState === "paused"
  // Where the open panel's card sits on screen ("x y w h"), published by
  // Panel.qml for tools/hero-set; empty string when the panel is closed.
  property string panelRect: ""

  Timer {
    id: phaseClear
    interval: 6000
    onTriggered: { root.phaseName = ""; root.phaseText = "" }
  }
  property int linesSeen: 0

  // Two timestamped step samples — pace is computed from the last minute, not
  // the session average, so the forecast reacts right away after a break.
  property var paceOld: null
  property var paceNew: null

  readonly property string scriptPath: {
    var dir = String(Qt.resolvedUrl("."))
    return dir.replace(/^file:\/\//, "") + "spacewalk-bridge.py"
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
    if (settings.phonePort !== undefined && settings.phonePort !== null
        && Math.round(Number(settings.phonePort)) !== phonePort) {
      phonePort = Math.round(Number(settings.phonePort))
      changedTransport = true
    }
    if (changedTransport && bridge.running) restart()
  }

  Timer {
    id: pendingWatchdog
    interval: 12000
    onTriggered: root.commandPending = false
  }

  function beginCommand(wantWalking) {
    intendedWalking = wantWalking
    commandPending = true
    pendingWatchdog.restart()
  }

  function send(command) {
    if (!bridge.running) {
      lastError = "the bridge is not running"
      return
    }
    bridge.write(command + "\n")
  }

  // The bridge re-sends speed and incline on its own a dozen or so seconds
  // after start — the treadmill ignores targets set before it reaches 1 km/h.
  //
  // We start with what the panel shows (targetSpeed/targetIncline), not the
  // settings values: with the belt stopped, the arrows change the former, and
  // the treadmill is expected to honor them after start.
  function start() {
    phaseText = "sending start..."
    phaseName = "sending"
    beginCommand(true)
    send("start " + Number(targetSpeed).toFixed(1) + " " + Math.round(targetIncline))
  }

  function stop() { phaseText = "stopping..."; beginCommand(false); send("stop") }
  function pause() { phaseText = "pausing..."; beginCommand(false); send("pause") }
  function setSpeed(kmh) {
    targetSpeed = kmh          // immediately in the panel, even when the belt is stopped
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
      if (msg.state !== "connected") { walking = false; commandPending = false; pendingWatchdog.stop() }
    } else if (msg.t === "error") {
      lastError = msg.msg || ""
    } else if (msg.t === "phase") {
      phaseName = msg.phase || ""
      phaseText = msg.text || ""
      // A start that never took, or a belt that would not spin up: stop the
      // pulse so the switch does not wait forever.
      if (["failed", "error", "partial"].indexOf(phaseName) !== -1) {
        commandPending = false
        pendingWatchdog.stop()
      }
      // The belt-is-moving message clears itself — the rest stays, because it describes state.
      if (phaseName === "running") phaseClear.restart()
    } else if (msg.t === "history") {
      history = msg.days || ({})
    } else if (msg.t === "belt") {
      beltState = msg.state || "stopped"
    } else if (msg.t === "targets") {
      if (msg.target_speed !== null && msg.target_speed !== undefined) targetSpeed = msg.target_speed
      if (msg.target_incline !== null && msg.target_incline !== undefined) targetIncline = msg.target_incline
    } else if (msg.t === "data") {
      applyData(msg)
    }
  }

  onWalkingChanged: if (commandPending && walking === intendedWalking) {
    commandPending = false
    pendingWatchdog.stop()
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
      // Keep a sample from ~60 s ago: the new one becomes the old one only after a minute.
      if (!paceNew) { paceNew = sample; paceOld = sample }
      else if (sample.time - paceNew.time >= 20000) { paceOld = paceNew; paceNew = sample }
      else paceNew = sample
    }
    if (msg.day_distance_m !== undefined) dayDistanceM = msg.day_distance_m
    if (msg.day_kcal !== undefined) dayKcal = msg.day_kcal
    if (msg.day_elapsed_s !== undefined) dayElapsedS = msg.day_elapsed_s

    // The grid draws from history, and today changes every second — we swap it
    // in live instead of waiting for the next directory read.
    if (msg.day !== undefined) {
      var next = ({})
      for (var k in history) next[k] = history[k]
      next[msg.day] = { steps: daySteps, distance_m: dayDistanceM,
                        kcal: dayKcal, elapsed_s: dayElapsedS }
      history = next
      today = msg.day
    }
  }

  // Started only after the object is built: with `running: true` written
  // directly, the process launches before stdout gets its SplitParser, and the
  // first (in practice, all) lines are lost.
  Component.onCompleted: bridge.running = true

  // State inspection from the terminal: `omarchy-shell spacewalk state`.
  // console.log from a user plugin does not reach the system journal, so this
  // is the only way to look inside the service live.
  IpcHandler {
    target: "spacewalk"

    function dump(): string {
      return JSON.stringify({
        linkState: root.linkState, linesSeen: root.linesSeen, speed: root.speed,
        incline: root.incline, targetSpeed: root.targetSpeed, targetIncline: root.targetIncline,
        beltState: root.beltState, phase: root.phaseName, phaseText: root.phaseText,
        walking: root.walking, daySteps: root.daySteps,
        dayKcal: root.dayKcal, dayElapsedS: root.dayElapsedS,
        dayDistanceM: root.dayDistanceM, lastError: root.lastError
      })
    }

    function start(): string { root.start(); return "ok" }
    function stop(): string { root.stop(); return "ok" }
    function speed(kmh: real): string { root.setSpeed(kmh); return "ok" }
    function incline(percent: real): string { root.setIncline(percent); return "ok" }

    // Panel from the keyboard and for tools/hero-set: via the shell, because the
    // panel lives in the bar and can exist once per monitor — there is one
    // service. panelRect is reported by the panel, empty string means "closed".
    function open(): void { if (root.shell) root.shell.summon("io.github.ncr.spacewalk") }
    function close(): void { if (root.shell) root.shell.hide("io.github.ncr.spacewalk") }
    function toggle(): void { if (root.shell) root.shell.toggle("io.github.ncr.spacewalk") }
    function panelRect(): string { return root.panelRect }
  }

  Process {
    id: bridge
    stdinEnabled: true
    command: {
      var argv = ["python3", root.scriptPath]
      if (root.address !== "") argv.push("--address", root.address)
      if (root.strideMeters > 0) argv.push("--stride", String(root.strideMeters))
      argv.push("--speed", String(root.startSpeed), "--incline", String(root.startIncline))
      // Server for the iPhone shortcut. We pass just the port — the bridge binds
      // to the Tailscale address, so it is not visible outside your own devices.
      if (root.phonePort > 0) argv.push("--serve", ":" + root.phonePort)
      return argv
    }
    stdout: SplitParser { onRead: function(line) { root.handleLine(line) } }
    stderr: SplitParser { onRead: function(line) { root.lastError = String(line) } }
    onExited: function(code) {
      root.linkState = "disconnected"
      root.walking = false
      // The bridge should never exit — it reconnects on its own. If it does die
      // (missing python-bleak, a syntax error), we bring it back after a moment, not in a loop.
      bridgeRestart.restart()
    }
  }

  Timer {
    id: bridgeRestart
    interval: 10000
    onTriggered: if (!bridge.running) bridge.running = true
  }
}
