import QtQuick
import QtQuick.Shapes
import qs.Commons
import qs.Ui
import "Model.js" as Model

// Today's heart rate as a line, with the bridge's notes pinned to it. Moving
// the cursor along the chart reads out the point under it (the panel shows
// `hoverPoint` in its caption line); coming near a marker opens its note.
Item {
  id: chart

  property var points: []
  property var notes: []
  property color foreground: Color.foreground
  property color accent: Color.accent
  property color urgent: Color.urgent
  // What the panel card is painted with: a load marker is a ring, and its
  // middle has to cover the line under it.
  property color background: Color.popups.background
  property string fontFamily: Style.font.family

  implicitHeight: Style.space(72)

  // Room on the left for the two scale numbers.
  readonly property real gutter: Style.space(26)
  readonly property real plotWidth: Math.max(1, width - gutter)
  readonly property var range: Model.heartRange(points)
  readonly property real step: Model.heartStep(points.length, plotWidth)
  readonly property var placedNotes: Model.placeNotes(points, notes)
  readonly property var segments: Model.heartSegments(points, plotWidth, height, range)

  function toPaths(runs) {
    return runs.map(function(run) { return run.map(function(p) { return Qt.point(p[0], p[1]) }) })
  }

  property int hoverIndex: -1
  readonly property var hoverPoint: hoverIndex >= 0 && hoverIndex < points.length
    ? points[hoverIndex] : null
  // The note whose marker the cursor is near, or null.
  property var activeNote: null

  function pointX(index) { return index * step }
  // A marker can outlive its point for a moment: past midnight the bridge
  // starts an empty chart while the cursor still rests on the old one.
  function pointY(index) {
    if (index < 0 || index >= points.length) return 0
    return Model.heartY(points[index][1], range, height)
  }

  // All markers sit on the line. A speed or incline change made while walking
  // says what the belt did and is a ring; the rest say what the heart did and
  // are filled: sudden ones in the urgent colour, slow ones in the text colour.
  // None takes the accent — that is the colour of the line while the belt runs.
  function isLoad(note) { return note.kind === "load" }
  function noteColor(note) {
    if (isLoad(note)) return background
    return note.kind === "drift" || note.kind === "recovery" ? foreground : urgent
  }

  function track(x) {
    hoverIndex = Model.heartIndexAt(x, points.length, plotWidth)
    var reach = Style.space(7)
    var nearest = null
    for (var i = 0; i < placedNotes.length; i++) {
      var distance = Math.abs(pointX(placedNotes[i].index) - x)
      if (distance <= reach) { reach = distance; nearest = placedNotes[i] }
    }
    activeNote = nearest
  }

  function release() { hoverIndex = -1; activeNote = null }

  // The scale: the top and bottom of the range, in the gutter.
  Repeater {
    model: [chart.range.high, chart.range.low]
    Text {
      required property var modelData
      required property int index
      width: chart.gutter - Style.space(6)
      y: index === 0 ? -Math.round(height * 0.3) : chart.height - Math.round(height * 0.7)
      horizontalAlignment: Text.AlignRight
      text: modelData
      color: chart.foreground
      opacity: 0.45
      font.family: chart.fontFamily
      font.pixelSize: Style.font.caption
    }
  }

  Item {
    id: plot
    x: chart.gutter
    width: chart.plotWidth
    height: chart.height

    // Guard over the whole plot, as on the day grid: on a fast move the
    // MouseArea's exit can fail to arrive and the last readout would stick.
    HoverHandler { onHoveredChanged: if (!hovered) chart.release() }

    Repeater {
      model: [0, plot.height - 1]
      Rectangle {
        required property var modelData
        y: modelData
        width: plot.width
        height: 1
        color: Util.alpha(chart.foreground, 0.12)
      }
    }

    // Where the strap was away: the points on either side are not neighbours in time.
    Repeater {
      model: Model.heartBreaks(chart.points)
      Rectangle {
        required property var modelData
        x: Math.round(chart.pointX(modelData) - chart.step / 2)
        width: 1
        height: plot.height
        color: Util.alpha(chart.foreground, 0.22)
      }
    }

    // Belt stopped: dimmed. Belt running: the accent at full strength. The
    // difference in strength carries it in themes whose accent is the text colour.
    Shape {
      anchors.fill: parent
      preferredRendererType: Shape.CurveRenderer

      ShapePath {
        strokeColor: Util.alpha(chart.foreground, 0.4)
        strokeWidth: 1.5
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        joinStyle: ShapePath.RoundJoin
        PathMultiline { paths: chart.toPaths(chart.segments.resting) }
      }

      ShapePath {
        strokeColor: chart.accent
        strokeWidth: 1.5
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        joinStyle: ShapePath.RoundJoin
        PathMultiline { paths: chart.toPaths(chart.segments.walking) }
      }
    }

    // The point under the cursor.
    Rectangle {
      visible: chart.hoverPoint !== null
      x: chart.hoverPoint ? Math.round(chart.pointX(chart.hoverIndex)) : 0
      width: 1
      height: plot.height
      color: Util.alpha(chart.foreground, 0.35)
    }

    Repeater {
      model: chart.placedNotes
      Rectangle {
        required property var modelData
        readonly property bool active: chart.activeNote !== null
          && chart.activeNote.at === modelData.at && chart.activeNote.kind === modelData.kind
        readonly property real size: Style.space(active ? 9 : 6)
        width: size
        height: size
        radius: size / 2
        x: chart.pointX(modelData.index) - size / 2
        y: chart.pointY(modelData.index) - size / 2
        color: chart.noteColor(modelData)
        border.width: chart.isLoad(modelData) ? 1.5 : 0
        border.color: chart.foreground
      }
    }

    // The tooltip hangs on an item placed at the active marker; on the chart
    // as a whole it would sit centered over it, away from what it describes.
    Item {
      id: noteAnchor
      width: 1
      height: 1
      x: chart.activeNote ? chart.pointX(chart.activeNote.index) : 0
      y: chart.activeNote ? chart.pointY(chart.activeNote.index) - Style.space(6) : 0

      PanelToolTip {
        delay: 0
        visible: chart.activeNote !== null
        text: chart.activeNote
              ? Model.formatClock(chart.activeNote.at) + " — " + chart.activeNote.text : ""
        fontFamily: chart.fontFamily
      }
    }

    MouseArea {
      anchors.fill: parent
      hoverEnabled: true
      acceptedButtons: Qt.NoButton
      onPositionChanged: function(mouse) { chart.track(mouse.x) }
      onExited: chart.release()
    }
  }
}
