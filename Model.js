.pragma library

// Liczenie postępu i przewidywanej godziny końca. Trzymane osobno od widoku,
// żeby dało się to sprawdzić bez uruchamiania shella.

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

// Kroki na minutę z dwóch próbek. Zwraca 0, gdy próbki nie pozwalają nic policzyć.
function paceFromSamples(older, newer) {
  if (!older || !newer) return 0
  var seconds = (newer.time - older.time) / 1000
  var steps = newer.steps - older.steps
  if (seconds < 5 || steps <= 0) return 0
  return steps / (seconds / 60)
}

// Kroki na minutę wyliczone z prędkości taśmy — używane, gdy nie ma jeszcze
// dwóch próbek albo bieżnia stoi i pokazujemy prognozę dla ustawionej prędkości.
function paceFromSpeed(speedKmh, strideMeters) {
  var stride = strideMeters > 0 ? strideMeters : 0.68
  if (!(speedKmh > 0)) return 0
  return (speedKmh * 1000 / 60) / stride
}

// Minuty do celu przy danym tempie. -1 znaczy „nie da się powiedzieć".
function minutesToGoal(steps, goal, stepsPerMinute) {
  var left = remaining(steps, goal)
  if (left === 0) return 0
  if (!(stepsPerMinute > 0)) return -1
  return left / stepsPerMinute
}

// "15:42" — godzina osiągnięcia celu przy danym tempie. Pusty tekst, gdy nieznana.
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
  return (m / 1000).toFixed(2).replace(".", ",") + " km"
}

function formatDuration(seconds) {
  var total = Math.max(0, Math.round(seconds || 0))
  var h = Math.floor(total / 3600)
  var m = Math.floor((total % 3600) / 60)
  if (h > 0) return h + " h " + String(m).padStart(2, "0") + " min"
  return m + " min"
}

// Podpis pod paskiem postępu: ile zostało i o której koniec.
function goalCaption(steps, goal, stepsPerMinute, now) {
  var left = remaining(steps, goal)
  if (left === 0) return "cel osiągnięty"
  var minutes = minutesToGoal(steps, goal, stepsPerMinute)
  var text = "zostało " + formatSteps(left)
  if (minutes < 0) return text
  var clock = finishClock(now, minutes)
  return text + " — koniec ok. " + clock + " (" + Math.round(minutes) + " min)"
}
