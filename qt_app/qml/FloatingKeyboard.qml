import QtQuick
import QtQuick.Layouts

Rectangle {
    id: root

    property var target: null
    property bool targetMultiline: false
    property bool minimized: false
    property bool uppercase: true
    property bool symbolMode: false
    property bool positioned: false

    property color panelColor: "#121A26"
    property color keyColor: "#182334"
    property color keyPressedColor: "#23344B"
    property color borderColor: "#26364B"
    property color textColor: "#F4F7FB"
    property color mutedTextColor: "#91A3B9"
    property color accentColor: "#23B7D9"

    readonly property real expandedHeight: 308

    width: Math.min(780, parent ? parent.width - 24 : 780)
    height: minimized ? 48 : expandedHeight
    visible: false
    z: 1000
    radius: 14
    color: panelColor
    border.color: borderColor
    border.width: 1
    clip: true

    // Consume también los toques en el pequeño espacio entre teclas. Sin este
    // manejador el evento atravesaba el teclado flotante y cambiaba el foco a
    // un control de la ventana que estaba debajo.
    TapHandler {
        id: focusKeeper
        gesturePolicy: TapHandler.WithinBounds
        onPressedChanged: {
            if (pressed && root.target)
                root.target.forceActiveFocus()
        }
    }

    function showFor(item, multiline) {
        target = item
        targetMultiline = multiline === true
        visible = true
        minimized = false
        if (!positioned && parent) {
            x = Math.max(8, (parent.width - width) / 2)
            y = Math.max(8, parent.height - expandedHeight - 12)
            positioned = true
        }
        clampToWindow()
        if (target)
            target.forceActiveFocus()
    }

    function reopen() {
        visible = true
        minimized = false
        if (!positioned && parent) {
            x = Math.max(8, (parent.width - width) / 2)
            y = Math.max(8, parent.height - expandedHeight - 12)
            positioned = true
        }
        clampToWindow()
        if (target)
            target.forceActiveFocus()
    }

    function clampToWindow() {
        if (!parent)
            return
        x = Math.max(8, Math.min(x, parent.width - width - 8))
        y = Math.max(8, Math.min(y, parent.height - height - 8))
    }

    function selectionStart() {
        if (!target || target.selectionStart === undefined)
            return target ? target.cursorPosition : 0
        return Math.min(target.selectionStart, target.selectionEnd)
    }

    function selectionEnd() {
        if (!target || target.selectionEnd === undefined)
            return target ? target.cursorPosition : 0
        return Math.max(target.selectionStart, target.selectionEnd)
    }

    function insertText(value) {
        if (!target || target.readOnly === true)
            return
        var start = selectionStart()
        var end = selectionEnd()
        if (end > start)
            target.remove(start, end)
        target.cursorPosition = start
        target.insert(start, value)
        target.cursorPosition = start + value.length
        target.forceActiveFocus()
    }

    function backspace() {
        if (!target || target.readOnly === true)
            return
        var start = selectionStart()
        var end = selectionEnd()
        if (end > start) {
            target.remove(start, end)
            target.cursorPosition = start
        } else if (start > 0) {
            target.remove(start - 1, start)
            target.cursorPosition = start - 1
        }
        target.forceActiveFocus()
    }

    function moveCursor(offset) {
        if (!target)
            return
        var next = Math.max(0, Math.min(target.length, target.cursorPosition + offset))
        target.cursorPosition = next
        target.forceActiveFocus()
    }

    function enter() {
        if (targetMultiline)
            insertText("\n")
        else
            minimized = true
    }

    component KeyButton: Rectangle {
        id: key
        property string keyLabel: ""
        property string keyValue: keyLabel
        property real keyWidth: 1
        property var keyAction: null

        Layout.fillWidth: true
        Layout.fillHeight: true
        Layout.preferredWidth: 50 * keyWidth
        radius: 8
        color: keyTap.pressed ? root.keyPressedColor : root.keyColor
        border.color: root.borderColor
        border.width: 1

        Text {
            anchors.centerIn: parent
            text: key.keyLabel
            color: root.textColor
            font.pixelSize: 17
            font.weight: Font.DemiBold
        }

        TapHandler {
            id: keyTap
            onPressedChanged: {
                if (pressed && root.target)
                    root.target.forceActiveFocus()
            }
            onTapped: {
                if (key.keyAction)
                    key.keyAction()
                else
                    root.insertText(key.keyValue)
            }
        }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 48
            color: "#0E1622"

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 12
                anchors.rightMargin: 8
                spacing: 8

                Item {
                    Layout.fillWidth: true
                    Layout.fillHeight: true

                    Row {
                        anchors.verticalCenter: parent.verticalCenter
                        spacing: 8
                        Text {
                            text: "TECLADO ZEUZ"
                            color: root.textColor
                            font.pixelSize: 14
                            font.weight: Font.Bold
                            font.letterSpacing: 1
                        }
                        Text {
                            text: "Arrastra para mover"
                            color: root.mutedTextColor
                            font.pixelSize: 12
                        }
                    }

                    DragHandler {
                        target: root
                        xAxis.minimum: 8
                        xAxis.maximum: root.parent ? root.parent.width - root.width - 8 : 8
                        yAxis.minimum: 8
                        yAxis.maximum: root.parent ? root.parent.height - root.height - 8 : 8
                    }
                }

                Rectangle {
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 34
                    radius: 8
                    color: minimizeTap.pressed ? root.keyPressedColor : root.keyColor
                    Text {
                        anchors.centerIn: parent
                        text: root.minimized ? "□" : "—"
                        color: root.textColor
                        font.pixelSize: 18
                        font.weight: Font.Bold
                    }
                    TapHandler {
                        id: minimizeTap
                        onTapped: {
                            root.minimized = !root.minimized
                            root.clampToWindow()
                        }
                    }
                }

                Rectangle {
                    Layout.preferredWidth: 40
                    Layout.preferredHeight: 34
                    radius: 8
                    color: closeTap.pressed ? "#713243" : root.keyColor
                    Text {
                        anchors.centerIn: parent
                        text: "×"
                        color: root.textColor
                        font.pixelSize: 22
                    }
                    TapHandler {
                        id: closeTap
                        onTapped: root.visible = false
                    }
                }
            }
        }

        ColumnLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            Layout.margins: 8
            spacing: 1
            visible: !root.minimized

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 1
                Repeater {
                    model: ["1", "2", "3", "4", "5", "6", "7", "8", "9", "0"]
                    delegate: KeyButton { keyLabel: modelData }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 1
                Repeater {
                    model: root.symbolMode
                           ? ["!", "@", "#", "$", "%", "^", "&", "*", "?", "="]
                           : ["Q", "W", "E", "R", "T", "Y", "U", "I", "O", "P"]
                    delegate: KeyButton {
                        keyLabel: root.symbolMode || root.uppercase
                                  ? modelData : modelData.toLowerCase()
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 1
                Repeater {
                    model: root.symbolMode
                           ? ["~", "`", "|", "\\", "<", ">", "[", "]", "{", "}"]
                           : ["A", "S", "D", "F", "G", "H", "J", "K", "L", "_"]
                    delegate: KeyButton {
                        keyLabel: root.symbolMode || modelData === "_" || root.uppercase
                                  ? modelData : modelData.toLowerCase()
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 1
                Repeater {
                    model: root.symbolMode
                           ? [";", "'", "\"", ",", "-", "_", "/", ":", "+", "."]
                           : ["Z", "X", "C", "V", "B", "N", "M", "-", "/", ":"]
                    delegate: KeyButton {
                        keyLabel: root.symbolMode
                                  || modelData.length !== 1 || modelData < "A" || modelData > "Z"
                                  ? modelData
                                  : root.uppercase ? modelData : modelData.toLowerCase()
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                Layout.fillHeight: true
                spacing: 1

                KeyButton {
                    keyLabel: root.symbolMode ? "ABC" : "#+="
                    keyValue: ""
                    keyAction: function() { root.symbolMode = !root.symbolMode }
                }
                KeyButton {
                    keyLabel: root.uppercase ? "Aa" : "aA"
                    keyValue: ""
                    visible: !root.symbolMode
                    keyAction: function() { root.uppercase = !root.uppercase }
                }
                KeyButton {
                    keyLabel: "←"
                    keyValue: ""
                    keyAction: function() { root.moveCursor(-1) }
                }
                KeyButton {
                    keyLabel: "→"
                    keyValue: ""
                    keyAction: function() { root.moveCursor(1) }
                }
                KeyButton { keyLabel: "ESPACIO"; keyValue: " "; keyWidth: 2.8 }
                KeyButton { keyLabel: "." }
                KeyButton { keyLabel: "+" }
                KeyButton { keyLabel: "(" }
                KeyButton { keyLabel: ")" }
                KeyButton {
                    keyLabel: "⌫"
                    keyValue: ""
                    keyAction: function() { root.backspace() }
                }
                KeyButton {
                    keyLabel: "↵"
                    keyValue: ""
                    keyAction: function() { root.enter() }
                }
            }
        }
    }

    onWidthChanged: if (positioned) clampToWindow()
    onHeightChanged: if (positioned) clampToWindow()
}
