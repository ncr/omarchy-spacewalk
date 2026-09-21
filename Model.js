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
// A point is [unix time, bpm, speed, incline, walking]. The bridge saves one a
// second; older files have one per 5 s, and points from before the walking
// flag have four items.

// What the belt and the walker were doing at a point: "resting" (belt
// stopped), "walking", or "empty" (belt running with nobody on it).
function heartState(point) {
  if (!(point[2] > 0)) return "resting"
  return point.length > 4 && !point[4] ? "empty" : "walking"
}

// The horizontal axis is seconds of strap data, not the clock: a stretch with
// the strap away (longer than HEART_BREAK_SECONDS between two points) is
// squeezed to HEART_BREAK_WIDTH, or two walks six hours apart would be two
// slivers at the chart's edges. Not the point count either — files hold points
// at two rates.
var HEART_BREAK_SECONDS = 30
var HEART_BREAK_WIDTH = 5
var HEART_MIN_SPAN = 600          // unzoomed, the chart spans at least ten minutes
var HEART_ZOOM_MIN = 120          // two minutes: the closest the wheel goes

// For each point, its place on that axis, counted from the first point.
function heartOffsets(points) {
  var out = new Array(points ? points.length : 0)
  for (var i = 0; i < out.length; i++) {
    if (i === 0) { out[0] = 0; continue }
    var gap = points[i][0] - points[i - 1][0]
    out[i] = out[i - 1] + (gap > HEART_BREAK_SECONDS ? HEART_BREAK_WIDTH : Math.max(gap, 0))
  }
  return out
}

function heartTotal(offsets) {
  return offsets.length > 0 ? offsets[offsets.length - 1] : 0
}

// How many seconds the chart's width stands for. `zoom` is that number as set
// with the wheel; 0 means everything there is.
function heartSpan(offsets, zoom) {
  return zoom > 0 ? zoom : Math.max(heartTotal(offsets), HEART_MIN_SPAN)
}

// First index with offsets[index] >= target.
function heartSearch(offsets, target) {
  var lo = 0, hi = offsets.length
  while (lo < hi) {
    var mid = (lo + hi) >> 1
    if (offsets[mid] < target) lo = mid + 1
    else hi = mid
  }
  return lo
}

// The first point the chart shows. The newest point always sits on the right
// edge and the rest run leftwards from it.
function heartFirst(offsets, zoom) {
  if (!(zoom > 0)) return 0
  return Math.min(heartSearch(offsets, heartTotal(offsets) - zoom), Math.max(offsets.length - 1, 0))
}

function heartX(index, offsets, span, width) {
  return width - (heartTotal(offsets) - offsets[index]) / span * width
}

// One notch of the wheel: a fifth closer, or a quarter farther. Zooming out
// past everything there is returns 0, "all", which then grows with the day.
function heartZoom(zoom, offsets, closer) {
  var span = heartSpan(offsets, zoom)
  if (closer) return Math.max(HEART_ZOOM_MIN, Math.round(span * 0.8))
  var wider = Math.round(span * 1.25)
  return wider >= heartTotal(offsets) ? 0 : wider
}

function heartZoomLabel(zoom) {
  return zoom > 0 ? formatDuration(zoom) + " shown" : ""
}

// The chart's vertical range: that of the points shown, opened up to at least
// 30 bpm and snapped to tens, so the scale does not twitch with every point.
function heartRange(points, first) {
  if (!points || points.length === 0) return { low: 60, high: 120 }
  var low = points[first || 0][1], high = low
  for (var i = (first || 0) + 1; i < points.length; i++) {
    if (points[i][1] < low) low = points[i][1]
    if (points[i][1] > high) high = points[i][1]
  }
  low = Math.floor((low - 3) / 10) * 10
  high = Math.ceil((high + 3) / 10) * 10
  while (high - low < 30) { high += 10; if (high - low < 30) low -= 10 }
  return { low: low, high: high }
}

function heartY(bpm, range, height) {
  var share = (bpm - range.low) / (range.high - range.low)
  return (1 - share) * (height - 2) + 1
}

// The line as [x, y] runs, one set per heartState, so the chart can draw each
// in its own colour. A run ends where the strap was away and where the state
// changes; there the next run begins at the previous spot, so the line stays
// in one piece.
//
// How finely it is drawn follows the zoom: points that land within half a
// pixel of each other become one spot at their mean. Zoomed out that is a
// minute of readings per spot, zoomed in every second gets its own.
function heartSegments(points, offsets, first, span, width, height, range) {
  var out = { resting: [], walking: [], empty: [] }
  var run = [], state = "resting"
  var spotX = 0, sum = 0, count = 0

  function flush() {
    if (count === 0) return
    run.push([spotX, heartY(sum / count, range, height)])
    sum = 0
    count = 0
  }
  function close() {
    flush()
    // A lone spot has no line to it; doubled, the round cap draws it as a dot.
    if (run.length === 1) run.push([run[0][0] + 0.01, run[0][1]])
    if (run.length > 0) out[state].push(run)
    run = []
  }

  for (var i = first; i < points.length; i++) {
    var x = heartX(i, offsets, span, width)
    var nowState = heartState(points[i])
    var broken = i > first && points[i][0] - points[i - 1][0] > HEART_BREAK_SECONDS
    if (i > first && (broken || nowState !== state)) {
      flush()
      var previous = run[run.length - 1]
      close()
      if (!broken) run.push(previous)
    } else if (count > 0 && x - spotX >= 0.5) {
      flush()
    }
    state = nowState
    if (count === 0) spotX = x
    sum += points[i][1]
    count++
  }
  close()
  return out
}

// Where the line passes at a point: the mean of the readings drawn into the
// same spot. A marker placed at the point's own reading would float off the
// line once the zoom averages many readings into one spot.
function heartLineY(index, points, offsets, first, span, width, height, range) {
  var reach = span / width * 0.5        // seconds that make half a pixel, as in heartSegments
  var sum = 0, count = 0
  for (var i = index; i >= first && offsets[index] - offsets[i] <= reach; i--) { sum += points[i][1]; count++ }
  for (var k = index + 1; k < points.length && offsets[k] - offsets[index] <= reach; k++) { sum += points[k][1]; count++ }
  return heartY(sum / count, range, height)
}

// Indexes of the shown points that come right after the strap was away.
function heartBreaks(points, first) {
  var out = []
  for (var i = first + 1; i < points.length; i++)
    if (points[i][0] - points[i - 1][0] > HEART_BREAK_SECONDS) out.push(i)
  return out
}

// The shown point nearest to x, -1 with nothing to show.
function heartIndexAt(x, offsets, first, span, width) {
  if (offsets.length === 0) return -1
  var target = heartTotal(offsets) - (width - x) / width * span
  var hi = heartSearch(offsets, target)
  if (hi >= offsets.length) hi = offsets.length - 1
  if (hi > first && target - offsets[hi - 1] < offsets[hi] - target) hi--
  return Math.max(hi, first)
}

// Each note with the index of the point it belongs to. A note whose moment is
// not among the shown points is left out.
function placeNotes(points, notes, first) {
  var out = []
  if (!points || !notes || points.length === 0) return out
  for (var n = 0; n < notes.length; n++) {
    var at = notes[n].at
    var lo = first, hi = points.length - 1
    while (lo < hi) {
      var mid = (lo + hi) >> 1
      if (points[mid][0] < at) lo = mid + 1
      else hi = mid
    }
    if (lo > first && at - points[lo - 1][0] < points[lo][0] - at) lo--
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
