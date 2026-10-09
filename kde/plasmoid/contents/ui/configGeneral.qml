import QtQuick
import QtQuick.Controls as QQC2
import org.kde.kirigami as Kirigami
import org.kde.kcmutils as KCM

// The settings of the Omarchy widget's manifest.json, in a Plasma dialog, and
// what the goal counts.
KCM.SimpleKCM {
    property string cfg_goalKind
    property alias cfg_address: address.text
    property alias cfg_dailyGoal: dailyGoal.value
    property real cfg_distanceGoal
    property alias cfg_calorieGoal: calorieGoal.value
    property real cfg_startSpeed
    property alias cfg_startIncline: startIncline.value
    property real cfg_strideMeters
    property alias cfg_phonePort: phonePort.value
    property alias cfg_heartAddress: heartAddress.text
    property alias cfg_heartLimit: heartLimit.value
    // Set from the panel icon's menu, not here; declared so the dialog has
    // somewhere to put it.
    property bool cfg_showRemaining

    // Plasma hands every page the defaults too, for its reset markers.
    property string cfg_goalKindDefault
    property string cfg_addressDefault
    property int cfg_dailyGoalDefault
    property real cfg_distanceGoalDefault
    property int cfg_calorieGoalDefault
    property real cfg_startSpeedDefault
    property int cfg_startInclineDefault
    property real cfg_strideMetersDefault
    property int cfg_phonePortDefault
    property string cfg_heartAddressDefault
    property int cfg_heartLimitDefault
    property bool cfg_showRemainingDefault

    Kirigami.FormLayout {
        QQC2.ComboBox {
            id: goalKind
            objectName: "goalKind"
            Kirigami.FormData.label: "Goal counts:"
            textRole: "text"
            valueRole: "value"
            readonly property var kinds: ["steps", "distance", "calories"]
            model: [
                { value: "steps", text: "Steps" },
                { value: "distance", text: "Distance" },
                { value: "calories", text: "Calories" }
            ]
            // Not indexOfValue(): Plasma sets cfg_goalKind while it creates the
            // page, before the box has its model, and that binding would not
            // look again.
            currentIndex: Math.max(0, kinds.indexOf(cfg_goalKind))
            onActivated: cfg_goalKind = currentValue
        }

        // One goal for each kind, kept apart, so switching back finds the old one.
        QQC2.SpinBox {
            id: dailyGoal
            objectName: "dailyGoal"
            visible: goalKind.currentValue === "steps"
            Kirigami.FormData.label: "Daily goal:"
            from: 1
            to: 100000
            stepSize: 500
            editable: true
            textFromValue: function(value) { return value + " steps" }
            valueFromText: function(text) { return parseInt(text) || 0 }
        }

        // In tenths of a kilometre.
        QQC2.SpinBox {
            id: distanceGoal
            objectName: "distanceGoal"
            visible: goalKind.currentValue === "distance"
            Kirigami.FormData.label: "Daily goal:"
            from: 1
            to: 1000
            stepSize: 5
            editable: true
            value: Math.round(cfg_distanceGoal * 10)
            onValueModified: cfg_distanceGoal = value / 10
            textFromValue: function(value) { return (value / 10).toFixed(1) + " km" }
            valueFromText: function(text) { return Math.round(parseFloat(text.replace(",", ".")) * 10) || 0 }
        }

        QQC2.SpinBox {
            id: calorieGoal
            objectName: "calorieGoal"
            visible: goalKind.currentValue === "calories"
            Kirigami.FormData.label: "Daily goal:"
            from: 1
            to: 10000
            stepSize: 50
            editable: true
            textFromValue: function(value) { return value + " kcal" }
            valueFromText: function(text) { return parseInt(text) || 0 }
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Treadmill"
        }

        QQC2.TextField {
            id: address
            Kirigami.FormData.label: "Address:"
            placeholderText: "Any FTMS treadmill"
        }

        // In tenths: 1.0–6.0 km/h is what the SpaceWalk 3S declares.
        QQC2.SpinBox {
            id: startSpeed
            Kirigami.FormData.label: "Speed on start:"
            from: 10
            to: 60
            value: Math.round(cfg_startSpeed * 10)
            onValueModified: cfg_startSpeed = value / 10
            textFromValue: function(value) { return (value / 10).toFixed(1) + " km/h" }
            valueFromText: function(text) { return Math.round(parseFloat(text.replace(",", ".")) * 10) }
        }

        QQC2.SpinBox {
            id: startIncline
            Kirigami.FormData.label: "Incline on start:"
            from: 0
            to: 9
            textFromValue: function(value) { return value + "%" }
            valueFromText: function(text) { return parseInt(text) || 0 }
        }

        // In centimetres; 0 takes the steps the treadmill counts itself.
        QQC2.SpinBox {
            id: stride
            Kirigami.FormData.label: "Stride length:"
            from: 0
            to: 150
            value: Math.round(cfg_strideMeters * 100)
            onValueModified: cfg_strideMeters = value / 100
            textFromValue: function(value) { return value === 0 ? "From the treadmill" : value + " cm" }
            valueFromText: function(text) { return parseInt(text) || 0 }
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Heart rate strap"
        }

        QQC2.TextField {
            id: heartAddress
            Kirigami.FormData.label: "Address:"
            placeholderText: "Any strap; \"off\" for none"
        }

        QQC2.SpinBox {
            id: heartLimit
            Kirigami.FormData.label: "Note a rate above:"
            from: 0
            to: 230
            textFromValue: function(value) { return value === 0 ? "Off" : value + " bpm" }
            valueFromText: function(text) { return parseInt(text) || 0 }
        }

        Kirigami.Separator {
            Kirigami.FormData.isSection: true
            Kirigami.FormData.label: "Apple Health"
        }

        QQC2.SpinBox {
            id: phonePort
            Kirigami.FormData.label: "Sync port:"
            from: 0
            to: 65535
            editable: true
            // No thousands separator in a port number.
            textFromValue: function(value) { return value === 0 ? "Off" : String(value) }
            valueFromText: function(text) { return parseInt(text) || 0 }
        }
    }
}
