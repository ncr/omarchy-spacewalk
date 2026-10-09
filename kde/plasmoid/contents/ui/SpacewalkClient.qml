import QtQuick
import org.kde.plasma.workspace.dbus as DBus

// The treadmill as the panel sees it, kept from the bridge's D-Bus face
// (docs/dbus.md). Property and function names follow the Omarchy widget's
// Service.qml, so the views port almost line for line.
//
// Plasma's D-Bus module, as checked on Plasma 6.6: property values from the
// first read come wrapped (take .value) but those from PropertiesChanged come
// plain, a signal calls the function named "dbus" + its name, and a call must
// not set a signature or it goes out without its arguments.
Item {
    id: root

    property string busName: "io.github.ncr.Spacewalk"
    readonly property string objectPath: "/io/github/ncr/Spacewalk"
    readonly property string interfaceName: "io.github.ncr.Spacewalk1"

    // What the belt starts with until the bridge reports targets of its own.
    property real startSpeed: 2.5
    property real startIncline: 3

    // ---- state read by the views

    readonly property bool serviceRunning: watcher.registered
    // starting | releasing | scanning | found | connecting | connected |
    // disconnected | not_found | stopping, and "no_service" without the bridge.
    readonly property string linkState: serviceRunning ? read("LinkState", "starting") : "no_service"
    readonly property bool connected: linkState === "connected"
    readonly property string device: read("Device", "")
    readonly property real speed: read("Speed", 0)
    readonly property real incline: read("Incline", 0)
    readonly property bool walking: connected && speed > 0.1
    // running | paused | stopped — from the treadmill's status messages.
    readonly property string beltState: read("BeltState", "stopped")
    readonly property bool paused: beltState === "paused"
    readonly property string today: read("Day", "")
    readonly property int daySteps: read("DaySteps", 0)
    readonly property int dayDistanceM: read("DayDistanceM", 0)
    readonly property int dayKcal: read("DayKcal", 0)
    readonly property int dayElapsedS: read("DayElapsedS", 0)
    readonly property int sessionElapsedS: read("SessionElapsedS", 0)
    readonly property string heartState: read("HeartState", "idle")
    readonly property int heartBpm: read("HeartBpm", 0)
    readonly property string heartDevice: read("HeartDevice", "")
    readonly property int heartBattery: read("HeartBattery", -1)

    // What start and the arrows ask for. A stopped belt reports zeros, so the
    // panel shows these; set at once on a press, then confirmed by the bridge.
    property real targetSpeed: startSpeed
    property real targetIncline: startIncline
    readonly property real busTargetSpeed: read("TargetSpeed", NaN)
    readonly property real busTargetIncline: read("TargetIncline", NaN)
    // The bridge confirms every change, and a confirmation can come after the
    // next click: taken at once, it pulled the tile back and the click was
    // lost. So for a moment after a change of our own the bridge's word waits,
    // and then the last one counts.
    onBusTargetSpeedChanged: if (!speedHold.running && !isNaN(busTargetSpeed)) targetSpeed = busTargetSpeed
    onBusTargetInclineChanged: if (!inclineHold.running && !isNaN(busTargetIncline)) targetIncline = busTargetIncline
    Timer {
        id: speedHold
        interval: 1500
        onTriggered: if (!isNaN(root.busTargetSpeed)) root.targetSpeed = root.busTargetSpeed
    }
    Timer {
        id: inclineHold
        interval: 1500
        onTriggered: if (!isNaN(root.busTargetIncline)) root.targetIncline = root.busTargetIncline
    }
    onStartSpeedChanged: if (isNaN(busTargetSpeed)) targetSpeed = startSpeed
    onStartInclineChanged: if (isNaN(busTargetIncline)) targetIncline = startIncline

    // Totals from recent days: {"2026-09-01": {steps, distance_m, kcal, elapsed_s}}.
    // The bridge sends the files as of its start; today is swapped in live.
    readonly property string historyJson: read("History", "{}")
    readonly property var history: {
        var days = {}
        try { days = JSON.parse(historyJson) } catch (e) { days = {} }
        if (today !== "")
            days[today] = { steps: daySteps, distance_m: dayDistanceM,
                            kcal: dayKcal, elapsed_s: dayElapsedS }
        return days
    }

    // Start progress. The belt-is-moving message clears itself; the others
    // describe state and stay.
    property string phaseName: ""
    property string phaseText: ""
    readonly property string busPhase: read("Phase", "")
    readonly property string busPhaseText: read("PhaseText", "")
    onBusPhaseChanged: {
        phaseName = busPhase
        // A start that never took: stop the pulse so the switch does not wait forever.
        if (["failed", "error", "partial"].indexOf(busPhase) !== -1) endCommand()
        if (busPhase === "running") phaseClear.restart()
    }
    onBusPhaseTextChanged: phaseText = busPhaseText
    Timer {
        id: phaseClear
        interval: 6000
        onTriggered: { root.phaseName = ""; root.phaseText = "" }
    }

    // The bridge's latest error, or one of our calls failing — whichever came last.
    property string lastError: ""
    readonly property string busError: read("LastError", "")
    onBusErrorChanged: lastError = busError

    // A command sent to the belt, not yet reflected in its readings: the
    // switch throws to `intendedWalking` at once and pulses until the belt
    // catches up. The belt takes seconds to spin up, hence the watchdog.
    property bool commandPending: false
    property bool intendedWalking: false
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
    function endCommand() {
        commandPending = false
        pendingWatchdog.stop()
    }
    onWalkingChanged: if (commandPending && walking === intendedWalking) endCommand()
    onConnectedChanged: if (!connected) endCommand()

    // Two timestamped samples of the day's totals: pace from the last minute,
    // not the session average, so the forecast reacts right after a break.
    property var paceOld: null
    property var paceNew: null
    onDayStepsChanged: takeSample()
    onDayDistanceMChanged: takeSample()
    onDayKcalChanged: takeSample()
    function takeSample() {
        var sample = { time: Date.now(), steps: daySteps, distance_m: dayDistanceM, kcal: dayKcal }
        if (!paceNew) { paceNew = sample; paceOld = sample }
        else if (sample.time - paceNew.time >= 20000) { paceOld = paceNew; paceNew = sample }
        else paceNew = sample
    }

    // Today's heart rate chart: points are [unix time, bpm, speed, incline,
    // walking], notes {at, kind, text, bpm}. Six hours a second at most.
    property var heartPoints: []
    property var heartNotes: []
    readonly property int heartPointsMax: 21600

    property bool reconnecting: false

    // ---- commands

    // The belt starts at the bridge's targets: the arrows hand every change
    // to it, belt running or not, and settings seed them through Configure.
    function start() {
        phaseText = "sending start..."
        phaseName = "sending"
        beginCommand(true)
        call("Start", null, null, endCommand)
    }
    function stop() { phaseText = "stopping..."; beginCommand(false); call("Stop", null, null, endCommand) }
    function pause() { phaseText = "pausing..."; beginCommand(false); call("Pause", null, null, endCommand) }
    // Shown at once; a refused value gives way to the bridge's own again.
    function setSpeed(kmh) {
        targetSpeed = kmh
        speedHold.restart()
        call("SetSpeed", [new DBus.double(kmh)], null, function() {
            root.targetSpeed = isNaN(root.busTargetSpeed) ? root.startSpeed : root.busTargetSpeed
        })
    }
    function setIncline(percent) {
        targetIncline = Math.round(percent)
        inclineHold.restart()
        call("SetIncline", [new DBus.double(Math.round(percent))], null, function() {
            root.targetIncline = isNaN(root.busTargetIncline) ? root.startIncline : root.busTargetIncline
        })
    }
    // A fresh bridge and Bluetooth link; the belt is neither started nor stopped.
    function reconnect() {
        if (reconnecting) return
        lastError = ""
        endCommand()
        phaseName = ""
        phaseText = ""
        reconnecting = true
        call("Reconnect", null, function() { root.reconnecting = false },
             function() { root.reconnecting = false })
    }
    // The bridge's command line; the same arguments again change nothing.
    // The first call also starts the service through D-Bus activation.
    function configure(args) { call("Configure", [args]) }

    // ---- plumbing

    function read(name, fallback) {
        var value = unwrap(props.properties[name])
        return value === undefined || value === null ? fallback : value
    }

    function unwrap(value) {
        return value !== null && typeof value === "object" && value.value !== undefined
            ? value.value : value
    }

    function call(member, args, onDone, onFailed) {
        var message = { service: busName, path: objectPath, iface: interfaceName, member: member }
        if (args) message.arguments = args
        DBus.SessionBus.asyncCall(message, function(reply) {
            if (onDone) onDone(reply)
        }, function(reply) {
            root.lastError = reply.error && reply.error.message ? reply.error.message
                                                                : member + " failed"
            if (onFailed) onFailed(reply)
        })
    }

    function loadHeartSeries() {
        call("GetHeartSeries", null, function(reply) {
            try {
                var series = JSON.parse(root.unwrap(reply.value))
                root.heartPoints = series.points.slice(-root.heartPointsMax)
                root.heartNotes = series.notes
            } catch (e) {
                console.warn("spacewalk: unreadable heart rate series:", e)
            }
        })
    }

    function addHeartPoint(point) {
        var last = heartPoints.length > 0 ? heartPoints[heartPoints.length - 1][0] : 0
        // A point the series already carried can arrive once more right after it.
        if (point && point[0] > last)
            heartPoints = heartPoints.concat([point]).slice(-heartPointsMax)
    }

    DBus.Properties {
        id: props
        busType: DBus.BusType.Session
        service: root.busName
        path: root.objectPath
        iface: root.interfaceName
    }

    DBus.DBusServiceWatcher {
        id: watcher
        busType: DBus.BusType.Session
        watchedService: root.busName
        // A new service starts from defaults and announces only what differs
        // from them; whatever the old one said last must not linger.
        onRegisteredChanged: if (registered) { props.updateAll(); seriesReload.restart() }
    }

    DBus.SignalWatcher {
        busType: DBus.BusType.Session
        service: root.busName
        path: root.objectPath
        iface: root.interfaceName

        function dbusHeartPoint(point) {
            try { root.addHeartPoint(JSON.parse(root.unwrap(point))) } catch (e) {}
        }
        function dbusHeartNote(note) {
            try { root.heartNotes = root.heartNotes.concat([JSON.parse(root.unwrap(note))]) } catch (e) {}
        }
        // The bridge sends a reloaded chart in chunks, one signal each.
        function dbusHeartSeriesChanged() { seriesReload.restart() }
    }

    Timer {
        id: seriesReload
        interval: 300
        onTriggered: root.loadHeartSeries()
    }

    Component.onCompleted: loadHeartSeries()
}
