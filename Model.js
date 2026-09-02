.pragma library

// Progress math and the predicted finish time. Kept apart from the view so it
// can be checked without launching the shell.

function clamp(value, low, high) {
  return Math.max(low, Math.min(high, value))
}

function progress(steps, goal) {
  if (!(goal > 0)) return 0
  return clamp(steps / goal, 0, 1)
}

function remaining(steps, goal) {
  return Math.max(0, Math.round(goal - steps))
}

// Steps per minute from two samples. Returns 0 when the samples allow no estimate.
function paceFromSamples(older, newer) {
  if (!older || !newer) return 0
  var seconds = (newer.time - older.time) / 1000
  var steps = newer.steps - older.steps
  if (seconds < 5 || steps <= 0) return 0
  return steps / (seconds / 60)
}

// Steps per minute derived from belt speed — used when two samples are not in
// yet, or the treadmill is stopped and we forecast for the set speed.
function paceFromSpeed(speedKmh, strideMeters) {
  var stride = strideMeters > 0 ? strideMeters : 0.68
  if (!(speedKmh > 0)) return 0
  return (speedKmh * 1000 / 60) / stride
}

// Minutes to the goal at a given pace. -1 means "cannot tell".
function minutesToGoal(steps, goal, stepsPerMinute) {
  var left = remaining(steps, goal)
  if (left === 0) return 0
  if (!(stepsPerMinute > 0)) return -1
  return left / stepsPerMinute
}

// "15:42" — the hour the goal is reached at a given pace. Empty text when unknown.
function finishClock(now, minutes) {
  if (minutes < 0) return ""
  var end = new Date(now.getTime() + minutes * 60000)
  var hh = String(end.getHours()).padStart(2, "0")
  var mm = String(end.getMinutes()).padStart(2, "0")
  return hh + ":" + mm
}

function formatSteps(steps) {
  var n = Math.round(steps || 0)
  return String(n).replace(/\B(?=(\d{3})+(?!\d))/g, " ")
}

function formatDistance(meters) {
  var m = Math.round(meters || 0)
  if (m < 1000) return m + " m"
  return (m / 1000).toFixed(2) + " km"
}

function formatDuration(seconds) {
  var total = Math.max(0, Math.round(seconds || 0))
  var h = Math.floor(total / 3600)
  var m = Math.floor((total % 3600) / 60)
  if (h > 0) return h + " h " + String(m).padStart(2, "0") + " min"
  return m + " min"
}

// Caption under the progress bar: how much is left and when it ends.
function goalCaption(steps, goal, stepsPerMinute, now) {
  var left = remaining(steps, goal)
  if (left === 0) return "goal reached"
  var minutes = minutesToGoal(steps, goal, stepsPerMinute)
  var text = formatSteps(left) + " to go"
  if (minutes < 0) return text
  var clock = finishClock(now, minutes)
  return text + " — done around " + clock + " (" + Math.round(minutes) + " min)"
}

// Caption for a past day — in the spot where today shows the finish forecast.
// Without it the panel jumped on every click on a grid cell.
function pastDayCaption(steps, goal) {
  if (steps <= 0) return "no walking"
  if (steps >= goal) return "goal reached (" + Math.round(steps / goal * 100) + "%)"
  return formatSteps(goal - steps) + " short of the goal"
}

// ------------------------------------------------------------------ day grid

// Day key in the bridge files' format: "2026-09-01".
function dayKey(date) {
  var m = String(date.getMonth() + 1)
  var d = String(date.getDate())
  return date.getFullYear() + "-" + (m.length < 2 ? "0" + m : m) + "-" + (d.length < 2 ? "0" + d : d)
}

function parseKey(key) {
  var p = String(key).split("-")
  return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]))
}

// A day's fill level, measured against the GOAL, not against the best day:
// full color means "done", not "more than yesterday".
function dayLevel(steps, goal) {
  if (!(steps > 0)) return 0
  var p = goal > 0 ? steps / goal : 0
  if (p >= 1) return 4
  if (p >= 0.75) return 3
  if (p >= 0.5) return 2
  return 1
}

// Days to draw: enough weeks back that the last column ends on today and
// every column starts on a Monday.
function gridDays(history, todayDate, weeks) {
  var out = []
  var end = new Date(todayDate.getFullYear(), todayDate.getMonth(), todayDate.getDate())
  // 0 = Sunday in JS; we want Monday–Sunday columns
  var trailing = (end.getDay() + 6) % 7          // days since Monday
  var lastMonday = new Date(end.getTime() - trailing * 86400000)
  var start = new Date(lastMonday.getTime() - (weeks - 1) * 7 * 86400000)

  for (var i = 0; i < weeks * 7; i++) {
    var date = new Date(start.getTime() + i * 86400000)
    var key = dayKey(date)
    var rec = history && history[key] ? history[key] : null
    out.push({
      key: key,
      date: date,
      steps: rec ? rec.steps : 0,
      distance_m: rec ? rec.distance_m : 0,
      kcal: rec ? rec.kcal : 0,
      elapsed_s: rec ? rec.elapsed_s : 0,
      future: date.getTime() > end.getTime()
    })
  }
  return out
}

// Average over the days you actually walked. Days without a walk would drag it
// down until it said nothing about the walking itself.
function averageSteps(history) {
  var sum = 0, days = 0
  for (var k in history) {
    if (history[k].steps > 0) { sum += history[k].steps; days++ }
  }
  return days > 0 ? { steps: Math.round(sum / days), days: days } : { steps: 0, days: 0 }
}

function daysWithGoal(history, goal) {
  var n = 0
  for (var k in history) if (history[k].steps >= goal) n++
  return n
}

var MONTHS = ["January", "February", "March", "April", "May", "June",
              "July", "August", "September", "October", "November", "December"]

function formatDay(date) {
  return MONTHS[date.getMonth()] + " " + date.getDate()
}
