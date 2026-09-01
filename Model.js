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

// Podpis dla dnia z przeszłości — w miejscu, gdzie dla dzisiaj stoi prognoza
// końca. Bez niego panel skakał przy każdym kliknięciu w kratkę.
function pastDayCaption(steps, goal) {
  if (steps <= 0) return "bez marszu"
  if (steps >= goal) return "cel osiągnięty (" + Math.round(steps / goal * 100) + "%)"
  return "zabrakło " + formatSteps(goal - steps) + " do celu"
}

// ---------------------------------------------------------------- kratka dni

// Klucz dnia w formacie plików mostu: "2026-09-01".
function dayKey(date) {
  var m = String(date.getMonth() + 1)
  var d = String(date.getDate())
  return date.getFullYear() + "-" + (m.length < 2 ? "0" + m : m) + "-" + (d.length < 2 ? "0" + d : d)
}

function parseKey(key) {
  var p = String(key).split("-")
  return new Date(Number(p[0]), Number(p[1]) - 1, Number(p[2]))
}

// Stopień wypełnienia dnia, liczony względem CELU, nie względem najlepszego dnia:
// pełny kolor znaczy „wyrobione", a nie „więcej niż wczoraj".
function dayLevel(steps, goal) {
  if (!(steps > 0)) return 0
  var p = goal > 0 ? steps / goal : 0
  if (p >= 1) return 4
  if (p >= 0.75) return 3
  if (p >= 0.5) return 2
  return 1
}

// Dni do narysowania: tyle tygodni wstecz, żeby ostatnia kolumna kończyła się
// na dziś, a każda kolumna zaczynała się w poniedziałek.
function gridDays(history, todayDate, weeks) {
  var out = []
  var end = new Date(todayDate.getFullYear(), todayDate.getMonth(), todayDate.getDate())
  // 0 = niedziela w JS; chcemy kolumny poniedziałek–niedziela
  var trailing = (end.getDay() + 6) % 7          // ile dni od poniedziałku
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

// Dni z rzędu z osiągniętym celem, licząc wstecz. Dzisiejszy dzień wchodzi do
// passy dopiero po osiągnięciu celu, ale jego brak jej nie zrywa — dzień trwa.
function streak(history, goal, todayDate) {
  var count = 0
  var cursor = new Date(todayDate.getFullYear(), todayDate.getMonth(), todayDate.getDate())
  var first = true
  while (true) {
    var rec = history ? history[dayKey(cursor)] : null
    var steps = rec ? rec.steps : 0
    if (steps >= goal) count++
    else if (!first) break
    first = false
    cursor = new Date(cursor.getTime() - 86400000)
    if (count > 400) break
  }
  return count
}

function bestDay(history) {
  var best = 0
  for (var k in history) if (history[k].steps > best) best = history[k].steps
  return best
}

// Średnia z ostatnich `days` dni, licząc też dni bez ruchu — inaczej wychodzi
// średnia z dni, w których i tak się chodziło.
function averageSteps(history, todayDate, days) {
  var sum = 0
  var cursor = new Date(todayDate.getFullYear(), todayDate.getMonth(), todayDate.getDate())
  for (var i = 0; i < days; i++) {
    var rec = history ? history[dayKey(cursor)] : null
    sum += rec ? rec.steps : 0
    cursor = new Date(cursor.getTime() - 86400000)
  }
  return Math.round(sum / days)
}

function daysWithGoal(history, goal) {
  var n = 0
  for (var k in history) if (history[k].steps >= goal) n++
  return n
}

var MONTHS = ["stycznia", "lutego", "marca", "kwietnia", "maja", "czerwca",
              "lipca", "sierpnia", "września", "października", "listopada", "grudnia"]

function formatDay(date) {
  return date.getDate() + " " + MONTHS[date.getMonth()]
}
