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

  // Everything the day has; the chart draws the points from `first` on.
  property var points: []
  property var notes: []
  property color foreground: Color.foreground
  property color accent: Color.accent
  property color urgent: Color.urgent
  // What the panel card is painted with: a load marker is a ring, and its
  // middle has to cover the line under it.
  property color background: Color.popups.background
  property string fontFamily: Style.font.family

  // The plot, and under it the row of clock times.
  readonly property real plotHeight: Style.space(72)
  readonly property real axisHeight: Math.round(Style.font.caption * 1.9)
  implicitHeight: plotHeight + axisHeight

  // Room on the left for the two scale numbers.
  readonly property real gutter: Style.space(26)
  readonly property real plotWidth: Math.max(1, width - gutter)
  // The wheel zooms, anchored to the right edge: the newest point stays put and
  // `zoom` says how many seconds of strap data back from it fit the width.
  // 0 shows everything. The closer the zoom, the finer the line is drawn.
  property int zoom: 0
  readonly property var offsets: Model.heartOffsets(points)
  readonly property int first: Model.heartFirst(offsets, zoom)
  readonly property real span: Model.heartSpan(offsets, zoom)
  readonly property string zoomLabel: Model.heartZoomLabel(zoom)
  readonly property var range: Model.heartRange(points, first)
  readonly property var placedNotes: Model.placeNotes(points, notes, first)
  readonly property var segments: Model.heartSegments(points, offsets, first, span,
                                                      plotWidth, plotHeight, range)

  function toPaths(runs) {
    return runs.map(function(run) { return run.map(function(p) { return Qt.point(p[0], p[1]) }) })
  }

  property int hoverIndex: -1
  readonly property var hoverPoint: hoverIndex >= first && hoverIndex < points.length
    ? points[hoverIndex] : null
  // The note whose marker the cursor is near, or null.
  property var activeNote: null

  function pointX(index) {
    if (index < 0 || index >= offsets.length) return 0
    return Model.heartX(index, offsets, span, plotWidth)
  }
  // A marker can outlive its point for a moment: past midnight the bridge
  // starts an empty chart while the cursor still rests on the old one.
  function pointY(index) {
    if (index < first || index >= points.length) return 0
    return Model.heartLineY(index, points, offsets, first, span, plotWidth, plotHeight, range)
  }

  // All markers sit on the line. What the belt did is drawn in the text
  // colour: a small dot where it started or stopped, a ring where speed or
  // incline changed. What the heart did is a filled dot: sudden changes in the
  // urgent colour, slow ones in the text colour. Filled dots carry a rim in
  // the card's colour, which keeps them apart from a line of their own colour.
  function isLoad(note) { return note.kind === "load" }
  function isBelt(note) { return note.kind === "belt" }
  function noteColor(note) {
    if (isLoad(note)) return background
    if (isBelt(note)) return Qt.tint(background, Util.alpha(foreground, 0.75))
    return note.kind === "drift" || note.kind === "recovery" ? foreground : urgent
  }
  function noteSize(note, active) {
    if (isBelt(note)) return Style.space(active ? 8 : 5)
    return Style.space(active ? 9 : 7)
  }

  property real cursorX: -1

  function track(x) {
    cursorX = x
    hoverIndex = Model.heartIndexAt(x, offsets, first, span, plotWidth)
    var reach = Style.space(7)
    var nearest = null
    for (var i = 0; i < placedNotes.length; i++) {
      var distance = Math.abs(pointX(placedNotes[i].index) - x)
      if (distance <= reach) { reach = distance; nearest = placedNotes[i] }
    }
    activeNote = nearest
  }

  function release() { cursorX = -1; hoverIndex = -1; activeNote = null }

  // A touchpad sends the wheel in small pieces; one notch is 120 of them.
  property real wheelRest: 0
  function turn(delta) {
    wheelRest += delta
    while (Math.abs(wheelRest) >= 120) {
      zoom = Model.heartZoom(zoom, offsets, wheelRest > 0)
      wheelRest -= wheelRest > 0 ? 120 : -120
    }
    // The cursor has not moved, but another point is under it now.
    if (cursorX >= 0) track(cursorX)
  }

  // The scale: the top and bottom of the range, in the gutter.
  Repeater {
    model: [chart.range.high, chart.range.low]
    Text {
      required property var modelData
      required property int index
      width: chart.gutter - Style.space(6)
      y: index === 0 ? -Math.round(height * 0.3) : chart.plotHeight - Math.round(height * 0.7)
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
    height: chart.plotHeight

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
      model: Model.heartBreaks(chart.points, chart.first)
      Rectangle {
        required property var modelData
        // In the middle of the squeezed stretch between the two points.
        x: Math.round((chart.pointX(modelData) + chart.pointX(modelData - 1)) / 2)
        width: 1
        height: plot.height
        color: Util.alpha(chart.foreground, 0.22)
      }
    }

    // Belt stopped: dimmed. Walking: the accent at full strength — the
    // difference in strength carries it in themes whose accent is the text
    // colour. Belt running with nobody on it: the urgent colour.
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

      ShapePath {
        strokeColor: chart.urgent
        strokeWidth: 1.5
        fillColor: "transparent"
        capStyle: ShapePath.RoundCap
        joinStyle: ShapePath.RoundJoin
        PathMultiline { paths: chart.toPaths(chart.segments.empty) }
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
        readonly property real size: chart.noteSize(modelData, active)
        width: size
        height: size
        radius: size / 2
        x: chart.pointX(modelData.index) - size / 2
        y: chart.pointY(modelData.index) - size / 2
        color: chart.noteColor(modelData)
        // The rim is part of the size: a 7 px marker shows 5 px of colour.
        border.width: chart.isLoad(modelData) ? 1.5 : 1
        border.color: chart.isLoad(modelData) ? chart.foreground : chart.background
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
      onWheel: function(wheel) { chart.turn(wheel.angleDelta.y); wheel.accepted = true }
    }
  }
  // The time axis. A monospace digit is about 0.6 of the font size wide, which
  // is what the spacing of the labels is worked out from.
  Repeater {
    model: Model.heartTicks(chart.points, chart.offsets, chart.first, chart.span,
                            chart.plotWidth, Style.font.caption * 0.62)
    Item {
      required property var modelData
      x: chart.gutter + modelData.x
      y: chart.plotHeight

      Rectangle {
        x: -0.5
        width: 1
        height: Style.space(3)
        color: Util.alpha(chart.foreground, 0.3)
      }

      Text {
        // Centred under its tick, but kept inside the plot at both ends.
        x: Math.max(-modelData.x, Math.min(-width / 2, chart.plotWidth - modelData.x - width))
        y: Style.space(4)
        text: modelData.text
        color: chart.foreground
        opacity: 0.45
        font.family: chart.fontFamily
        font.pixelSize: Style.font.caption
      }
    }
  }
}
