"""Tests for the KDE Plasma widget in kde/plasmoid.

    python3 -m unittest discover -s kde/tests -v

The widget's parts run outside plasmashell (Harness.qml, offscreen) against a
fake bridge on a private D-Bus bus (fake_host.py) — never a treadmill. Needs
PyQt6 with QtQuick and QtTest, Plasma 6's QML modules, and dbus-daemon.

SPACEWALK_SHOTS=<dir> also saves pictures of the views there.
"""
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PACKAGE = ROOT / "kde" / "plasmoid"

try:
    from PyQt6.QtCore import Q_ARG, Q_RETURN_ARG, QDate, QDateTime, QMetaObject, QObject, QPointF, Qt, QTime, QUrl
    from PyQt6.QtGui import QGuiApplication
    from PyQt6.QtQuick import QQuickView
    from PyQt6.QtTest import QTest
except ImportError:
    QGuiApplication = None

host = None
app = None
view = None
commands_log = None
# Model.js groups thousands with a narrow no-break space, so a number never wraps.
NB = "\u202f"


def setUpModule():
    global host, app, view, commands_log
    if QGuiApplication is None:
        raise unittest.SkipTest("PyQt6 with QtQuick and QtTest is needed")
    if not shutil.which("dbus-daemon"):
        raise unittest.SkipTest("dbus-daemon is needed")
    host = subprocess.Popen([sys.executable, str(HERE / "fake_host.py")],
                            stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True)
    info = json.loads(host.stdout.readline())
    commands_log = Path(info["commands"])
    # Before Qt opens its session bus connection: the widget talks to the fake.
    os.environ["DBUS_SESSION_BUS_ADDRESS"] = info["address"]
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    app = QGuiApplication.instance() or QGuiApplication([sys.argv[0]])
    view = QQuickView()
    warnings = []
    view.engine().warnings.connect(lambda found: warnings.extend(w.toString() for w in found))
    view.setSource(QUrl.fromLocalFile(str(HERE / "Harness.qml")))
    if view.errors():
        raise RuntimeError("\n".join(e.toString() for e in view.errors()))
    view.show()
    until(lambda: client().property("daySteps") == 10042, what="first data from the fake bridge")
    if warnings:
        raise RuntimeError("QML warnings while loading:\n" + "\n".join(warnings))
    view.engine().warnings.connect(lambda found: print(*(w.toString() for w in found), sep="\n"))


def tearDownModule():
    if view:
        view.close()
    if host:
        host.stdin.close()
        host.wait(10)


# ---------------------------------------------------------------- helpers

def until(condition, timeout=5.0, what="condition"):
    deadline = time.monotonic() + timeout
    while True:
        value = condition()
        if value:
            return value
        if time.monotonic() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        QTest.qWait(20)


def root():
    return view.rootObject()


def js(value):
    """A JavaScript value (array, object) as plain Python."""
    return value.toVariant() if hasattr(value, "toVariant") else value


def prop(target, name):
    return js(target.property(name))


def client():
    return root().property("client")


def item(name):
    """The visual item with this objectName. Walks the item tree: what a
    Repeater makes has no QObject parent, so findChild misses it."""
    pending = [root()]
    while pending:
        current = pending.pop(0)
        if current.objectName() == name:
            return current
        pending.extend(current.childItems())
    raise AssertionError(f"no item named {name!r}")


def text(name):
    return item(name).property("text")


def invoke(target, method, *args):
    QMetaObject.invokeMethod(target, method, *(Q_ARG("QVariant", a) for a in args))


def invoke_returning(target, method, *args):
    return js(QMetaObject.invokeMethod(target, method, Q_RETURN_ARG("QVariant"),
                                       *(Q_ARG("QVariant", a) for a in args)))


def click(target, button=None):
    centre = target.mapToScene(QPointF(target.width() / 2, target.height() / 2)).toPoint()
    QTest.mouseClick(view, button or Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier, centre)


def bridge(line):
    """A line to the fake bridge, as if it came from the host."""
    host.stdin.write(line + "\n")
    host.stdin.flush()


def received():
    """Every command the fake bridge got so far."""
    return commands_log.read_text().split() if commands_log.exists() else []


# The fake bridge logs the tests' own prompts too; those never come from the widget.
TEST_ONLY = ("walk", "rest", "beat")


def received_since(mark):
    """Commands the widget sent since mark(), without the chart requests."""
    lines = commands_log.read_text().splitlines() if commands_log.exists() else []
    return [line for line in lines[mark:]
            if line != "heart-series" and line.split()[0] not in TEST_ONLY]


def mark():
    return len(commands_log.read_text().splitlines()) if commands_log.exists() else 0


def shot(name):
    folder = os.environ.get("SPACEWALK_SHOTS")
    if folder:
        Path(folder).mkdir(parents=True, exist_ok=True)
        view.grabWindow().save(str(Path(folder) / f"{name}.png"))


class WidgetTestCase(unittest.TestCase):
    def setUp(self):
        # Every test starts with the belt standing and no command in flight.
        bridge("rest")
        until(lambda: client().property("walking") is False, what="the belt to stand")
        invoke(client(), "endCommand")
        # ...and a goal of 10 000 steps, the mouse away from the grid.
        for view_ in (root().property("compact"), root().property("full")):
            view_.setProperty("goalKind", "steps")
            view_.setProperty("goal", 10000)
        root().property("compact").setProperty("showRemaining", False)
        QTest.mouseMove(view, item("amount").mapToScene(QPointF(2, 2)).toPoint())
        until(lambda: root().property("full").property("hoveredDay") is None, what="no day previewed")


# ---------------------------------------------------------------- the client

class ClientTests(WidgetTestCase):
    def test_reads_the_bridge(self):
        c = client()
        self.assertTrue(c.property("serviceRunning"))
        self.assertEqual(c.property("linkState"), "connected")
        self.assertEqual(c.property("device"), "URTM024")
        # As the fake bridge's "rest" reading left them (setUp).
        self.assertEqual(c.property("daySteps"), 10100)
        self.assertEqual(c.property("dayDistanceM"), 7040)
        self.assertEqual(c.property("today"), "2026-10-08")
        history = prop(c, "history")
        self.assertEqual(history["2026-10-07"]["steps"], 5000)
        # Today comes from the live totals, not the history the bridge started with.
        self.assertEqual(history["2026-10-08"]["steps"], c.property("daySteps"))

    def test_targets_start_from_the_settings_until_the_bridge_has_some(self):
        c = client()
        self.assertEqual(c.property("targetSpeed"), 2.5)
        self.assertEqual(c.property("targetIncline"), 3)

    def test_pace_samples_carry_every_total(self):
        # The forecast for a distance or calorie goal comes from these.
        sample = prop(client(), "paceNew")
        self.assertEqual((sample["steps"], sample["distance_m"], sample["kcal"]), (10100, 7040, 303))

    def test_walking_follows_the_readings(self):
        bridge("walk")
        until(lambda: client().property("walking"), what="walking")
        self.assertEqual(client().property("speed"), 2.5)
        self.assertEqual(client().property("daySteps"), 10100)

    def test_a_refused_call_shows_its_error(self):
        invoke(client(), "setSpeed", -1.0)
        until(lambda: client().property("lastError") == "speed must not be negative",
              what="the bridge's refusal")

    def test_without_the_bridge(self):
        orphan = invoke_returning(root(), "orphanClient")
        until(lambda: orphan.property("linkState") == "no_service", what="no_service")
        self.assertFalse(orphan.property("connected"))
        self.assertFalse(orphan.property("walking"))
        orphan.deleteLater()

    def test_settings_become_bridge_arguments(self):
        defaults = {"address": "", "strideMeters": 0, "startSpeed": 2.5, "startIncline": 3,
                    "phonePort": 0, "heartAddress": "", "heartLimit": 150}
        # The same command line the Omarchy widget starts the bridge with.
        self.assertEqual(invoke_returning(root(), "bridgeArgs", defaults),
                         ["--speed", "2.5", "--incline", "3", "--heart-limit", "150"])
        everything = dict(defaults, address=" 54:50:00:0D:E6:5A ", strideMeters=0.7,
                          phonePort=8787, heartAddress="off", heartLimit=0)
        self.assertEqual(invoke_returning(root(), "bridgeArgs", everything),
                         ["--address", "54:50:00:0D:E6:5A", "--stride", "0.7",
                          "--speed", "2.5", "--incline", "3", "--serve", ":8787",
                          "--heart-address", "off", "--heart-limit", "0"])


# ---------------------------------------------------------------- the popup

class PopupTests(WidgetTestCase):
    def test_shows_todays_numbers(self):
        until(lambda: text("amount") == f"10{NB}100", what="today's steps")
        self.assertEqual(text("stat-calories"), "303 kcal")
        self.assertEqual(text("stat-time"), "1 h 24 min")
        self.assertEqual(text("stat-distance"), "7.04 km")
        self.assertEqual(text("caption"), "goal reached")
        self.assertIn("steps a day", text("average"))
        # A standing belt: one of the idle phrases, no trouble.
        self.assertIn(text("heroMeta"), [p.upper() for p in (
            "Treadmill ready", "Waiting for the switch", "Zero steps will not grow", "Incline set, your move")])
        shot("popup")

    def test_numbers_follow_the_bridge(self):
        root().property("full").setProperty("goal", 20000)
        until(lambda: "to go" in text("caption"), what="a caption with steps to go")
        self.assertTrue(text("caption").startswith(f"9{NB}900 to go"))
        fill = item("progressFill")
        # The bar animates to its new width.
        until(lambda: abs(fill.property("width") / fill.parentItem().property("width") - 10100 / 20000) < 0.01,
              what="the bar at half")

    def test_switch_starts_and_pauses_the_belt(self):
        switch = item("beltSwitch")
        until(lambda: switch.property("enabled"), what="an enabled switch")
        start = mark()
        click(switch)
        until(lambda: received_since(start) == ["start"], what="start at the bridge")
        # Optimistic: the knob shows where the belt is headed straight away.
        self.assertTrue(switch.property("checked"))
        bridge("walk")
        until(lambda: client().property("walking"), what="walking")
        self.assertFalse(client().property("commandPending"))
        click(switch)
        until(lambda: received_since(start) == ["start", "pause"], what="pause at the bridge")
        shot("walking")

    def test_arrows_change_the_targets(self):
        start = mark()
        click(item("speed-up"))
        until(lambda: received_since(start) == ["speed 3.0"], what="speed 3.0")
        until(lambda: text("speed-value") == "3.0 km/h", what="the new target in the tile")
        click(item("incline-down"))
        until(lambda: received_since(start) == ["speed 3.0", "incline 2"], what="incline 2")
        # Clamped to what the treadmill declares: 1.0–6.0 km/h.
        for _ in range(8):
            click(item("speed-up"))
        until(lambda: text("speed-value") == "6.0 km/h", what="the top speed")
        self.assertEqual(received_since(start)[-1], "speed 6.0")
        invoke(client(), "setSpeed", 2.5)
        invoke(client(), "setIncline", 3)
        until(lambda: received_since(start)[-2:] == ["speed 2.5", "incline 3"], what="targets back")

    def test_r_restarts_the_bridge_and_leaves_the_belt_alone(self):
        starts = received().count("heart-series")
        start = mark()
        full = item("full")
        invoke(full, "forceActiveFocus")
        QTest.keyClick(view, Qt.Key.Key_R)
        # A fresh bridge asks for the day's chart once it is up.
        until(lambda: received().count("heart-series") > starts, what="a fresh bridge")
        until(lambda: client().property("linkState") == "connected", what="the link back")
        self.assertEqual(received_since(start), [])
        self.assertFalse(client().property("reconnecting"))

    def test_heart_chart(self):
        until(lambda: len(prop(client(), "heartPoints")) >= 2, what="the day's chart")
        self.assertTrue(item("heartSection").property("visible"))
        count = len(prop(client(), "heartPoints"))
        last = prop(client(), "heartPoints")[-1][0]
        bridge(f"beat {int(last) + 1}")
        until(lambda: len(prop(client(), "heartPoints")) == count + 1, what="a live point")
        self.assertIn("bpm today", text("heartCaption"))
        shot("heart")

    def test_errors_show_only_while_the_link_is_down(self):
        invoke(client(), "setSpeed", -1.0)
        until(lambda: client().property("lastError") != "", what="an error")
        # Connected: the bridge never clears its last error, so it stays hidden.
        self.assertFalse(item("lastError").property("visible"))

    def test_hovering_a_day_shows_that_day(self):
        cells = [c for c in item("dayGrid").childItems() if c.property("modelData")]
        yesterday = next(c for c in cells if c.property("modelData")["key"] == "2026-10-07") \
            if any(c.property("modelData")["key"] == "2026-10-07" for c in cells) else None
        if yesterday is None:
            self.skipTest("2026-10-07 is outside the 13 weeks the grid shows today")
        centre = yesterday.mapToScene(QPointF(4, 4)).toPoint()
        QTest.mouseMove(view, centre)
        until(lambda: text("amount") == f"5{NB}000", what="the hovered day's steps")
        self.assertEqual(text("stat-distance"), "3.50 km")
        self.assertEqual(text("caption"), f"5{NB}000 short of the goal")
        # The same day counted in distance.
        full = root().property("full")
        full.setProperty("goalKind", "distance")
        until(lambda: text("amount") == "3.50 km", what="the hovered day's distance")
        self.assertEqual(text("caption"), "6.50 km short of the goal")
        self.assertEqual(text("stat-steps"), f"5{NB}000")
        QTest.mouseMove(view, item("amount").mapToScene(QPointF(2, 2)).toPoint())
        until(lambda: text("amount") == "7.04 km", what="today again")

    def yesterday_cell(self):
        for cell in item("dayGrid").childItems():
            data = cell.property("modelData")
            if data and data["key"] == "2026-10-07":
                return cell
        self.skipTest("2026-10-07 is outside the 13 weeks the grid shows today")

    def test_distance_goal(self):
        full = root().property("full")
        full.setProperty("goalKind", "distance")
        until(lambda: text("amount") == "7.04 km", what="today's distance")
        # Distance moves out of the row under the number; steps take its place.
        self.assertEqual([text(f"stat-{n}") for n in ("calories", "time", "steps")],
                         ["303 kcal", "1 h 24 min", f"10{NB}100"])
        with self.assertRaises(AssertionError):
            item("stat-distance")
        self.assertTrue(text("caption").startswith("2.96 km to go"), text("caption"))
        # (3500 m + 7040 m) / 2 days
        self.assertEqual(text("average"), "You average 5.27 km a day")
        fill = item("progressFill")
        until(lambda: abs(fill.property("width") / fill.parentItem().property("width") - 0.704) < 0.01,
              what="the bar at 7.04 of 10 km")
        shot("distance")

    def test_calorie_goal(self):
        full = root().property("full")
        full.setProperty("goalKind", "calories")
        full.setProperty("goal", 400)
        until(lambda: text("amount") == "303 kcal", what="today's calories")
        self.assertEqual([text(f"stat-{n}") for n in ("steps", "time", "distance")],
                         [f"10{NB}100", "1 h 24 min", "7.04 km"])
        self.assertTrue(text("caption").startswith("97 kcal to go"), text("caption"))
        # (200 + 303) / 2 days
        self.assertEqual(text("average"), "You average 252 kcal a day")
        full.setProperty("goal", 300)
        until(lambda: text("caption") == "goal reached", what="the goal reached")

    def test_the_grid_measures_days_against_the_goal(self):
        cell = self.yesterday_cell()
        full = root().property("full")
        accent = full.property("accent")
        # 5000 of 10 000 steps: half way, not done.
        self.assertNotEqual(cell.property("color"), accent)
        # 3.5 km of 4 km: not done, though 5000 steps would be.
        full.setProperty("goalKind", "distance")
        full.setProperty("goal", 4000)
        QTest.qWait(50)
        self.assertNotEqual(cell.property("color"), accent)
        # 3.5 km of a 3 km goal: done.
        full.setProperty("goal", 3000)
        until(lambda: cell.property("color") == accent, what="yesterday done in distance")


# ---------------------------------------------------------------- the goal

def goal(name, *args):
    return invoke_returning(root(), "goalCall", name, list(args))


class GoalTests(unittest.TestCase):
    def test_kinds(self):
        self.assertEqual(goal("kind", "distance"), "distance")
        # An unknown or missing setting counts steps, as before there was a choice.
        self.assertEqual(goal("kind", "furlongs"), "steps")
        self.assertEqual(goal("kind", ""), "steps")

    def test_targets_from_the_settings(self):
        cfg = {"dailyGoal": 10000, "distanceGoal": 4.5, "calorieGoal": 350}
        self.assertEqual(goal("target", "steps", cfg), 10000)
        self.assertEqual(goal("target", "distance", cfg), 4500)
        self.assertEqual(goal("target", "calories", cfg), 350)

    def test_pace_from_samples(self):
        older = {"time": 0, "steps": 100, "distance_m": 50, "kcal": 10}
        newer = {"time": 60000, "steps": 190, "distance_m": 110, "kcal": 14}
        self.assertEqual(goal("paceFromSamples", "steps", older, newer), 90)
        self.assertEqual(goal("paceFromSamples", "distance", older, newer), 60)
        self.assertEqual(goal("paceFromSamples", "calories", older, newer), 4)
        # Samples from before the widget took distance along: no estimate.
        self.assertEqual(goal("paceFromSamples", "distance", {"time": 0, "steps": 1},
                              {"time": 60000, "steps": 90}), 0)

    def test_pace_from_speed(self):
        history = {"a": {"kcal": 100, "distance_m": 2000}, "b": {"kcal": 50, "distance_m": 1000}}
        # 3 km/h is 50 m a minute; the history burns 0.05 kcal a metre.
        self.assertEqual(goal("paceFromSpeed", "distance", 3.0, 0, history), 50)
        self.assertAlmostEqual(goal("paceFromSpeed", "calories", 3.0, 0, history), 2.5)
        self.assertAlmostEqual(goal("paceFromSpeed", "steps", 3.0, 0.5, history), 100)
        # Too little walking to tell the calories a metre: no forecast.
        self.assertEqual(goal("paceFromSpeed", "calories", 3.0, 0, {"a": {"kcal": 2, "distance_m": 40}}), 0)
        self.assertEqual(goal("paceFromSpeed", "distance", 0, 0, history), 0)

    def test_captions(self):
        ten = QDateTime(QDate(2026, 10, 8), QTime(10, 0))
        self.assertEqual(goal("caption", "distance", 1500, 5000, 50, ten),
                         "3.50 km to go — done around 11:10 (70 min)")
        self.assertEqual(goal("caption", "calories", 100, 400, 0, ten), "300 kcal to go")
        self.assertEqual(goal("pastDayCaption", "calories", 500, 400), "goal reached (125%)")
        self.assertEqual(goal("pastDayCaption", "distance", 0, 4000), "no walking")


class SettingsPageTests(unittest.TestCase):
    def setUp(self):
        # As Plasma hands them over: while it creates the page, not after.
        self.page = invoke_returning(root(), "settingsPage", {
            "goalKind": "distance", "dailyGoal": 10000, "distanceGoal": 5.0, "calorieGoal": 400})
        self.assertIsNotNone(self.page, "the settings page did not load")

    def tearDown(self):
        self.page.deleteLater()

    def child(self, name):
        return self.page.findChild(QObject, name)

    def test_shows_the_goal_of_the_chosen_kind(self):
        kind = self.child("goalKind")
        self.assertEqual(kind.property("currentValue"), "distance")
        self.assertEqual([self.child(n).property("visible")
                          for n in ("dailyGoal", "distanceGoal", "calorieGoal")], [False, True, False])
        self.assertEqual(self.child("distanceGoal").property("value"), 50)
        self.assertEqual(self.child("distanceGoal").property("displayText"), "5.0 km")

    def test_choosing_a_kind_saves_it(self):
        kind = self.child("goalKind")
        # As a pick from the list does: currentIndex, then activated.
        kind.setProperty("currentIndex", 2)
        QMetaObject.invokeMethod(kind, "activated", Q_ARG("int", 2))
        self.assertEqual(self.page.property("cfg_goalKind"), "calories")
        self.assertEqual([self.child(n).property("visible")
                          for n in ("dailyGoal", "distanceGoal", "calorieGoal")], [False, False, True])
        # The dialog's Defaults button sets the value back.
        self.page.setProperty("cfg_goalKind", "steps")
        self.assertEqual(kind.property("currentValue"), "steps")


# ---------------------------------------------------------------- the panel

class CompactTests(WidgetTestCase):
    def test_shows_steps_or_steps_left(self):
        compact = root().property("compact")
        until(lambda: text("compactNumber") == f"10{NB}100", what="steps in the panel")
        compact.setProperty("goal", 20000)
        compact.setProperty("showRemaining", True)
        until(lambda: text("compactNumber") == f"9{NB}900", what="steps left")
        shot("compact")

    def test_shows_what_the_goal_counts(self):
        compact = root().property("compact")
        compact.setProperty("goalKind", "distance")
        until(lambda: text("compactNumber") == "7.04 km", what="distance in the panel")
        compact.setProperty("showRemaining", True)
        until(lambda: text("compactNumber") == "2.96 km", what="distance left")
        compact.setProperty("goalKind", "calories")
        compact.setProperty("goal", 400)
        until(lambda: text("compactNumber") == "97 kcal", what="calories left")
        compact.setProperty("showRemaining", False)
        until(lambda: text("compactNumber") == "303 kcal", what="calories in the panel")
        # Past the goal there is nothing left.
        compact.setProperty("goal", 300)
        compact.setProperty("showRemaining", True)
        until(lambda: text("compactNumber") == "0 kcal", what="no calories left")
        shot("compact-calories")

    def test_left_click_opens_and_closes_the_popup(self):
        stub = root().property("plasmoidStub")
        stub.setProperty("expanded", False)
        click(root().property("compact"))
        until(lambda: stub.property("expanded"), what="expanded")
        click(root().property("compact"))
        until(lambda: not stub.property("expanded"), what="collapsed")

    def test_middle_click_starts_and_stops_the_belt(self):
        start = mark()
        click(root().property("compact"), Qt.MouseButton.MiddleButton)
        until(lambda: received_since(start) == ["start"], what="start")
        bridge("walk")
        until(lambda: client().property("walking"), what="walking")
        click(root().property("compact"), Qt.MouseButton.MiddleButton)
        until(lambda: received_since(start) == ["start", "stop"], what="stop")


# ---------------------------------------------------------------- the package

class PackageTests(unittest.TestCase):
    def test_metadata(self):
        meta = json.loads((PACKAGE / "metadata.json").read_text())
        self.assertEqual(meta["KPackageStructure"], "Plasma/Applet")
        self.assertEqual(meta["KPlugin"]["Id"], "io.github.ncr.spacewalk")
        self.assertEqual(meta["X-Plasma-API-Minimum-Version"], "6.0")

    def test_model_is_the_omarchy_widgets_own(self):
        # One model for both widgets; the package needs its own copy.
        self.assertEqual((PACKAGE / "contents/code/Model.js").read_text(),
                         (ROOT / "Model.js").read_text(),
                         "kde/plasmoid/contents/code/Model.js differs from Model.js — copy it over")

    def test_menu_offers_every_goal_kind(self):
        main = (PACKAGE / "contents/ui/main.qml").read_text()
        for name in ("steps", "distance", "calories"):
            self.assertIn(f'Plasmoid.configuration.goalKind = "{name}"', main)
            self.assertIn(f'{{ value: "{name}"', (PACKAGE / "contents/ui/configGeneral.qml").read_text())

    def test_settings_match_the_omarchy_manifest(self):
        import xml.etree.ElementTree as ET
        ns = {"k": "http://www.kde.org/standards/kcfg/1.0"}
        entries = {e.get("name") for e in ET.parse(PACKAGE / "contents/config/main.xml").iterfind(".//k:entry", ns)}
        manifest = json.loads((ROOT / "manifest.json").read_text())
        self.assertLessEqual(set(manifest["barWidget"]["defaults"]), entries)

    def test_settings_page_takes_every_setting(self):
        # Plasma hands the page cfg_<name> and cfg_<name>Default for every
        # entry, and warns about each one the page lacks.
        import re
        import xml.etree.ElementTree as ET
        ns = {"k": "http://www.kde.org/standards/kcfg/1.0"}
        entries = [e.get("name") for e in ET.parse(PACKAGE / "contents/config/main.xml").iterfind(".//k:entry", ns)]
        page = (PACKAGE / "contents/ui/configGeneral.qml").read_text()
        declared = set(re.findall(r"property\s+(?:alias|\w+)\s+(cfg_\w+)", page))
        for name in entries:
            self.assertIn(f"cfg_{name}", declared)
            self.assertIn(f"cfg_{name}Default", declared)

    @unittest.skipUnless(shutil.which("qmllint"), "qmllint is needed")
    def test_qml_lints_clean(self):
        files = sorted(str(p) for p in (PACKAGE / "contents").rglob("*.qml"))
        result = subprocess.run(["qmllint", *files], capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(shutil.which("kpackagetool6"), "kpackagetool6 is needed")
    def test_installs_with_kpackagetool(self):
        # Only --install honours --packageroot; --upgrade and --remove look in
        # the user's own plasmoids whatever it says (KF 6.24), so those are
        # left to kde/install.sh.
        with tempfile.TemporaryDirectory() as folder:
            result = subprocess.run(["kpackagetool6", "--type", "Plasma/Applet", "--packageroot", folder,
                                     "--install", str(PACKAGE)], capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            installed = Path(folder) / "io.github.ncr.spacewalk"
            self.assertTrue((installed / "contents/ui/main.qml").is_file())
            self.assertTrue((installed / "contents/code/Model.js").is_file())


if __name__ == "__main__":
    unittest.main()
