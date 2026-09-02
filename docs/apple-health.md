# Sending walks to Apple Health

Apple Health has no public API for writing from the outside — the only route that avoids
paid apps goes through **Shortcuts** on the iPhone and its "Log Health Sample" action.
The shortcut fetches walks from the computer over Tailscale, writes them to Health, and
acknowledges receipt so the same data doesn't land there twice.

Shortcuts can't record a workout as a whole (Workout) — three separate samples go in
instead: steps, distance and active energy. A real workout entry requires a paid app
that imports a `.fit`/`.tcx` file (RunGap, HealthFit).

## What the computer exposes

The server is off until you set the `phonePort` setting (Setup > Plugins; 8787 is the
usual choice). With a port set, the bridge listens on the **Tailscale address** (not on
localhost, not on the local network). To check from the computer:

```bash
curl http://$(tailscale ip -4):8787/pending
```

| Endpoint | What it does |
|---|---|
| `GET /pending` | walks the phone hasn't picked up yet |
| `GET /ack-all` | marks as sent whatever the last `/pending` returned |
| `GET /ack?ids=a,b` | marks the given walks |
| `GET /today` | daily totals, for a quick look |

A walk closes after 90 seconds without movement or when the treadmill disconnects.
Walks without a single step (the belt spinning with nobody on it) are not recorded.

Everything lives in `~/.local/state/omarchy-spacewalk/sessions.jsonl`, one line per
walk, with a `sent` flag.

## The shortcut on the iPhone

`your-computer` below is your machine's name in the tailnet (MagicDNS) — `tailscale status`
shows it. If the name doesn't resolve, use the raw address instead:
`http://100.x.y.z:8787`, where the address comes from `tailscale ip -4` on the computer.

1. **Get Contents of URL** — `http://your-computer:8787/pending`
2. **Get Dictionary Value** for `sessions` **in** Contents of URL
3. **Repeat with Each** item in Dictionary Value. First all the reads into named
   variables, only then the writes — otherwise you get zeros (why, below):
   - **Get Dictionary Value** for `end_text` **in** Repeat Item
   - **Get Dates from Input** ← turns the text into a date. Without it
     "Log Health Sample" receives a string instead of a date and the shortcut stalls.
   - **Set Variable** `date`
   - **Get Dictionary Value** for `steps` → **Set Variable** `steps`
   - **Get Dictionary Value** for `distance_m` → **Set Variable** `meters`
   - **Get Dictionary Value** for `kcal` → **Set Variable** `calories`
   - **Log Health Sample**: type *Steps*, value ← `steps`, date ← `date`
   - **Log Health Sample**: type *Walking + Running Distance*, unit *meters*,
     value ← `meters`, date ← `date`
   - **Log Health Sample**: type *Active Energy*, unit *kcal*,
     value ← `calories`, date ← `date`
4. After the loop — **outside it**, at the very end of the shortcut: **Get Contents
   of URL** → `http://your-computer:8787/ack-all`

Two things that are easy to trip on:

- **The value in every sample must be set explicitly.** A field left blank takes the
  input from the previous action, and when the previous action is a sample write, the
  input is empty → zero.
- **Every "Get Dictionary Value" creates a variable of the same name**, so without
  named variables it's easy to pick the wrong one.

Send distance in meters: 30 m expressed in kilometers is 0.03 and looks like zero.

The type in the "Log Health Sample" action can't be supplied as a variable — hence the
three separate actions. On first run iOS asks for permission to write to Health; without
it the action ends with an error.

Each session comes with fields ready-made for Shortcuts: `end_text` and `start_text`
(date with a space instead of `T`, because ISO with `T` sometimes fails to parse) plus
`distance_km`, in case kilometers are more convenient.

## When the shortcut doesn't work

Check whether the phone reached the computer at all — the bridge logs every request:

```bash
grep '"t":"request"' ~/.local/state/omarchy-spacewalk/bridge.log | tail
```

An entry with the phone's address and `200 OK` on `/pending` means the network and the
server work, and the problem is in the shortcut itself. No entry after `/ack-all` means
the shortcut stopped inside the loop before acknowledging — most often on the date or
on missing Health permission.

## Once a day, on its own

In Shortcuts → **Automation** tab → **+** → **Time of Day**: pick an hour, **Daily**,
and at the bottom **Run Immediately**. Without that last one iOS only shows a
notification you have to tap. Next → pick the shortcut. "Notify When Run" can be
turned off.

Pick the hour to suit the computer, since that's where the data comes from — if you
shut it down for the night, early evening is safer than 11 PM.

A failed attempt breaks nothing: walks stay in the queue until the shortcut
acknowledges them, so the next run picks up the backlog too. That's why a second
automation as a backup is worth adding — for example "when iPhone is connected to
charger".

The phone must have Tailscale on and a **valid node key**: when the key expires, the
device still shows in the list, but traffic doesn't pass and the shortcut ends with a
timeout. Check from the computer: `tailscale ping iphone`. The fix: log in again in
the Tailscale app, and to make it permanent — "Disable key expiry" in the admin panel.

## Double counting

Treadmill steps add to whatever Health has from other sources. Walking with the phone
on the desk, there's nothing to double. If you start walking with the iPhone in your
pocket or with an Apple Watch — remove the steps action from the shortcut, or they'll
be counted twice.
