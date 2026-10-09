.pragma library

// The widget's settings as the bridge's command line, the same arguments the
// Omarchy widget's Service.qml starts it with. The host restarts the bridge
// only when they change, so the same settings must give the same strings.
function bridgeArgs(cfg) {
    var argv = []
    var address = String(cfg.address || "").trim()
    if (address !== "") argv.push("--address", address)
    if (cfg.strideMeters > 0) argv.push("--stride", String(cfg.strideMeters))
    argv.push("--speed", String(cfg.startSpeed), "--incline", String(cfg.startIncline))
    // The bridge binds the phone server to the Tailscale address; just the port here.
    if (cfg.phonePort > 0) argv.push("--serve", ":" + cfg.phonePort)
    var heart = String(cfg.heartAddress || "").trim()
    if (heart !== "") argv.push("--heart-address", heart)
    argv.push("--heart-limit", String(cfg.heartLimit))
    return argv
}
