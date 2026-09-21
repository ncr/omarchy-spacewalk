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

// --------------------------------------------------------------- heart chart
//
// A point is [unix time, bpm, speed, incline, walking], one per 5 s of strap
// data. Points recorded before the walking flag have four items.

// What the belt and the walker were doing at a point: "resting" (belt
// stopped), "walking", or "empty" (belt running with nobody on it).
function heartState(point) {
  if (!(point[2] > 0)) return "resting"
  return point.length > 4 && !point[4] ? "empty" : "walking"
}

// The chart's vertical range: the data's own, opened up to at least 30 bpm and
// snapped to tens, so the scale does not twitch with every new point.
function heartRange(points) {
  if (!points || points.length === 0) return { low: 60, high: 120 }
  var low = points[0][1], high = points[0][1]
  for (var i = 1; i < points.length; i++) {
    if (points[i][1] < low) low = points[i][1]
    if (points[i][1] > high) high = points[i][1]
  }
  low = Math.floor((low - 3) / 10) * 10
  high = Math.ceil((high + 3) / 10) * 10
  while (high - low < 30) { high += 10; if (high - low < 30) low -= 10 }
  return { low: low, high: high }
}

// Points sit side by side no matter how much clock time lies between them: two
// walks six hours apart would otherwise be two slivers at the chart's edges.
// The newest point always sits on the right edge and the rest run leftwards
// from it, `span` points to the chart's width. Unzoomed, the span is all the
// points there are, but at least ten minutes' worth, so the first minute of a
// walk does not stretch across the whole width.
var HEART_MIN_POINTS = 120
var HEART_ZOOM_MIN_POINTS = 60      // five minutes: the closest the wheel goes
var HEART_BREAK_SECONDS = 30

function heartSpan(count, zoom) {
  return zoom > 0 ? zoom : Math.max(count, HEART_MIN_POINTS)
}

function heartStep(span, width) {
  return width / Math.max(span - 1, 1)
}

function heartX(index, count, span, width) {
  return width - (count - 1 - index) * heartStep(span, width)
}

// The points the chart shows at a zoom of `zoom` points (0: all of them).
function heartWindow(points, zoom) {
  if (!points) return []
  return zoom > 0 && zoom < points.length ? points.slice(points.length - zoom) : points
}

// One notch of the wheel: a fifth closer, or a quarter farther. Zooming out
// past everything there is returns 0, "all", which then grows with the day.
function heartZoom(zoom, count, closer) {
  var span = heartSpan(count, zoom)
  if (closer) return Math.max(HEART_ZOOM_MIN_POINTS, Math.round(span * 0.8))
  var wider = Math.round(span * 1.25)
  return wider >= count ? 0 : wider
}

function heartZoomLabel(zoom) {
  return zoom > 0 ? formatDuration(zoom * 5) + " shown" : ""
}

function heartY(bpm, range, height) {
  var share = (bpm - range.low) / (range.high - range.low)
  return Math.round((1 - share) * (height - 2)) + 1
}

// The line as [x, y] runs, one set per heartState, so the chart can draw each
// in its own colour. A run ends where the strap was away and where the state
// changes; there the next run begins at the previous point, so the line stays
// in one piece.
function heartSegments(points, width, height, range, span) {
  var out = { resting: [], walking: [], empty: [] }
  var run = [], state = "resting"
  function close() {
    // A lone point has no line to it; doubled, the round cap draws it as a dot.
    if (run.length === 1) run.push([run[0][0] + 0.01, run[0][1]])
    if (run.length > 0) out[state].push(run)
    run = []
  }
  for (var i = 0; i < points.length; i++) {
    var spot = [heartX(i, points.length, span, width), heartY(points[i][1], range, height)]
    var nowState = heartState(points[i])
    var broken = i > 0 && points[i][0] - points[i - 1][0] > HEART_BREAK_SECONDS
    if (i > 0 && (broken || nowState !== state)) {
      var previous = run[run.length - 1]
      close()
      if (!broken) run.push(previous)
    }
    state = nowState
    run.push(spot)
  }
  close()
  return out
}

// Indexes of the points that start a new run, for the divider lines.
function heartBreaks(points) {
  var out = []
  for (var i = 1; i < points.length; i++)
    if (points[i][0] - points[i - 1][0] > HEART_BREAK_SECONDS) out.push(i)
  return out
}

function heartIndexAt(x, count, span, width) {
  if (count === 0) return -1
  var fromRight = Math.round((width - x) / heartStep(span, width))
  return clamp(count - 1 - fromRight, 0, count - 1)
}

// Each note with the index of the point it belongs to. A note whose moment is
// not on the chart (older than the first point) is left out.
function placeNotes(points, notes) {
  var out = []
  if (!points || !notes || points.length === 0) return out
  for (var n = 0; n < notes.length; n++) {
    var at = notes[n].at
    var lo = 0, hi = points.length - 1
    while (lo < hi) {
      var mid = (lo + hi) >> 1
      if (points[mid][0] < at) lo = mid + 1
      else hi = mid
    }
    if (lo > 0 && at - points[lo - 1][0] < points[lo][0] - at) lo--
    if (Math.abs(points[lo][0] - at) > HEART_BREAK_SECONDS) continue
    out.push({ index: lo, at: at, kind: notes[n].kind, text: notes[n].text })
  }
  return out
}

function formatClock(unixSeconds) {
  var d = new Date(unixSeconds * 1000)
  return String(d.getHours()).padStart(2, "0") + ":" + String(d.getMinutes()).padStart(2, "0")
}

function formatLoad(speed, incline) {
  if (!(speed > 0)) return "belt stopped"
  return Number(speed).toFixed(1) + " km/h, " + Math.round(incline) + "%"
}

// The line above the chart while the cursor is on it.
function heartCaption(point) {
  return formatClock(point[0]) + " · " + point[1] + " bpm · " + formatLoad(point[2], point[3])
    + (heartState(point) === "empty" ? ", nobody on it" : "")
}

// The same line with the cursor elsewhere: the live rate and today's span.
function heartSummary(points, bpm, strapState) {
  var parts = []
  if (strapState === "connected") parts.push(bpm > 0 ? bpm + " bpm now" : "strap on, no reading yet")
  else if (strapState === "connecting") parts.push("connecting to the strap...")
  if (points && points.length > 0) {
    var low = points[0][1], high = points[0][1]
    for (var i = 1; i < points.length; i++) {
      if (points[i][1] < low) low = points[i][1]
      if (points[i][1] > high) high = points[i][1]
    }
    parts.push(low + "–" + high + " bpm today")
  }
  if (strapState !== "connected" && strapState !== "connecting" && parts.length > 0)
    parts.push("strap away")
  return parts.join(" · ")
}
