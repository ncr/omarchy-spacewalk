.pragma library
.import "Model.js" as Model

// What the daily goal counts: steps, distance or calories. Model.js is the
// Omarchy widget's and counts steps only; this puts the same captions and
// forecasts on any of the three. A goal is in the kind's own unit: steps,
// metres, kilocalories.

var KINDS = ["steps", "distance", "calories"]

function kind(name) {
  return KINDS.indexOf(name) !== -1 ? name : "steps"
}

// The goal from the widget's settings; the distance goal is set in km.
function target(name, cfg) {
  switch (kind(name)) {
    case "distance": return Math.round((cfg.distanceGoal || 0) * 1000)
    case "calories": return cfg.calorieGoal || 0
    default: return cfg.dailyGoal || 0
  }
}

// The counted amount from a day record ({steps, distance_m, kcal, elapsed_s}).
function value(name, record) {
  if (!record) return 0
  switch (kind(name)) {
    case "distance": return record.distance_m || 0
    case "calories": return record.kcal || 0
    default: return record.steps || 0
  }
}

// An amount as the panel shows it: steps as a bare number, the others with
// their unit.
function format(name, amount) {
  switch (kind(name)) {
    case "distance": return Model.formatDistance(amount)
    case "calories": return Model.formatSteps(amount) + " kcal"
    default: return Model.formatSteps(amount)
  }
}

// The same with a unit always: "10 100 steps".
function describe(name, amount) {
  return kind(name) === "steps" ? format(name, amount) + " steps" : format(name, amount)
}

// For "Show ... left to the goal".
function noun(name) {
  return kind(name)
}

// The three numbers under the big one: what the goal does not count, and the time.
function stats(name, record) {
  var r = record || {}
  var steps = { label: "steps", value: Model.formatSteps(r.steps) }
  var calories = { label: "calories", value: Math.round(r.kcal || 0) + " kcal" }
  var time = { label: "time", value: Model.formatDuration(r.elapsed_s) }
  var distance = { label: "distance", value: Model.formatDistance(r.distance_m) }
  switch (kind(name)) {
    case "distance": return [calories, time, steps]
    case "calories": return [steps, time, distance]
    default: return [calories, time, distance]
  }
}

// ------------------------------------------------------------------ the pace

function field(name) {
  switch (kind(name)) {
    case "distance": return "distance_m"
    case "calories": return "kcal"
    default: return "steps"
  }
}

// Units a minute from two samples ({time, steps, distance_m, kcal}); 0 when
// they allow no estimate.
function paceFromSamples(name, older, newer) {
  if (!older || !newer) return 0
  var key = field(name)
  if (older[key] === undefined || newer[key] === undefined) return 0
  var seconds = (newer.time - older.time) / 1000
  var amount = newer[key] - older[key]
  if (seconds < 5 || amount <= 0) return 0
  return amount / (seconds / 60)
}

// Calories per metre walked over the days in the history, the treadmill's own
// estimate; 0 before there is enough walking to tell.
function kcalPerMetre(history) {
  var kcal = 0, metres = 0
  for (var k in history) {
    kcal += history[k].kcal || 0
    metres += history[k].distance_m || 0
  }
  return metres >= 100 && kcal > 0 ? kcal / metres : 0
}

// Units a minute at a belt speed: the forecast before two samples are in, or
// with the belt stopped.
function paceFromSpeed(name, speedKmh, strideMeters, history) {
  if (!(speedKmh > 0)) return 0
  var metresPerMinute = speedKmh * 1000 / 60
  switch (kind(name)) {
    case "distance": return metresPerMinute
    case "calories": return metresPerMinute * kcalPerMetre(history)
    default: return Model.paceFromSpeed(speedKmh, strideMeters)
  }
}

// ---------------------------------------------------------------- captions

// Under the progress bar: how much is left and when it is done.
function caption(name, amount, goal, perMinute, now) {
  var left = Model.remaining(amount, goal)
  if (left === 0) return "goal reached"
  var text = format(name, left) + " to go"
  var minutes = Model.minutesToGoal(amount, goal, perMinute)
  if (minutes < 0) return text
  return text + " — done around " + Model.finishClock(now, minutes) + " (" + Math.round(minutes) + " min)"
}

// The same spot for a past day.
function pastDayCaption(name, amount, goal) {
  if (amount <= 0) return "no walking"
  if (amount >= goal) return "goal reached (" + Math.round(amount / goal * 100) + "%)"
  return format(name, goal - amount) + " short of the goal"
}

// Average over the days with some of it, as Model.averageSteps.
function average(name, history) {
  var sum = 0, days = 0
  for (var k in history) {
    var amount = value(name, history[k])
    if (amount > 0) { sum += amount; days++ }
  }
  return days > 0 ? Math.round(sum / days) : 0
}

function averageText(name, history) {
  return "You average " + describe(name, average(name, history)) + " a day"
}
