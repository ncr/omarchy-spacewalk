import QtQuick
import QtQuick.Shapes
import org.kde.kirigami as Kirigami

// A walker in mid-stride, drawn rather than loaded: Kirigami.Icon does not
// recolour an SVG from a file, and the walker has to follow the theme's text
// colour like the rest of the panel. Laid out on a 24 × 24 grid.
Item {
    id: walker
    property color color: Kirigami.Theme.textColor
    implicitWidth: Kirigami.Units.iconSizes.smallMedium
    implicitHeight: implicitWidth

    Shape {
        width: 24
        height: 24
        scale: Math.min(walker.width, walker.height) / 24
        transformOrigin: Item.TopLeft
        preferredRendererType: Shape.CurveRenderer

        ShapePath {
            fillColor: walker.color
            strokeColor: "transparent"
            PathAngleArc { centerX: 13.5; centerY: 3.5; radiusX: 2.2; radiusY: 2.2; startAngle: 0; sweepAngle: 360 }
        }

        ShapePath {
            fillColor: "transparent"
            strokeColor: walker.color
            strokeWidth: 2.4
            capStyle: ShapePath.RoundCap
            joinStyle: ShapePath.RoundJoin
            PathSvg {
                path: "M12.5 7.5 L10.5 14 M12.3 8.5 L8.5 11 L7 14 M12.3 8.5 L15 11.5 L18 12.5 "
                      + "M10.5 14 L13.5 17 L13 21.5 M10.5 14 L8.5 18 L5.5 20.5"
            }
        }
    }
}
