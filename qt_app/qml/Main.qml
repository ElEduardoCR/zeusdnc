import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Window

ApplicationWindow {
    id: window
    visible: true
    visibility: Window.FullScreen
    minimumWidth: 1024
    minimumHeight: 600
    color: "#0B1018"
    title: "Zeuz DNC"

    property color panel: "#121A26"
    property color panelRaised: "#182334"
    property color line: "#26364B"
    property color textMain: "#F4F7FB"
    property color textMuted: "#91A3B9"
    property color accent: "#23B7D9"
    property color success: "#42D392"
    property color danger: "#FF637D"

    font.family: "Inter"

    component Panel: Rectangle {
        radius: 18
        color: window.panel
        border.color: window.line
        border.width: 1
    }

    component ActionButton: Button {
        id: control
        property color buttonColor: window.accent
        font.pixelSize: 17
        font.weight: Font.DemiBold
        implicitHeight: 52
        background: Rectangle {
            radius: 13
            color: !control.enabled ? "#263140"
                  : control.down ? Qt.darker(control.buttonColor, 1.18)
                  : control.hovered ? Qt.lighter(control.buttonColor, 1.08)
                  : control.buttonColor
            Behavior on color { ColorAnimation { duration: 80 } }
        }
        contentItem: Text {
            text: control.text
            color: control.enabled ? "#071118" : "#708095"
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            font: control.font
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 14

        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 58
            spacing: 14

            Text {
                text: "ZEUZ"
                color: textMain
                font.pixelSize: 28
                font.weight: Font.Black
                font.letterSpacing: 2
            }

            Rectangle {
                Layout.preferredWidth: 1
                Layout.preferredHeight: 28
                color: line
            }

            Text {
                text: "DNC"
                color: textMuted
                font.pixelSize: 18
                font.weight: Font.Medium
            }

            Item { Layout.fillWidth: true }

            BusyIndicator {
                running: backend.busy
                visible: running
                palette.dark: accent
                Layout.preferredWidth: 34
                Layout.preferredHeight: 34
            }

            Rectangle {
                Layout.preferredWidth: sourceText.implicitWidth + 24
                Layout.preferredHeight: 36
                radius: 18
                color: backend.agentConfigured ? "#15382F" : panelRaised
                border.color: backend.agentConfigured ? "#2C6B58" : line
                Text {
                    id: sourceText
                    anchors.centerIn: parent
                    text: backend.sourceLabel
                    color: backend.agentConfigured ? success : textMuted
                    font.pixelSize: 13
                    font.weight: Font.DemiBold
                }
            }

            Text {
                text: backend.status
                color: backend.status === "Listo" ? success : textMuted
                font.pixelSize: 15
            }

            ActionButton {
                text: "AJUSTES"
                Layout.preferredWidth: 112
                buttonColor: panelRaised
                onClicked: settingsDialog.open()
            }
        }

        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            spacing: 14

            Panel {
                Layout.preferredWidth: Math.max(300, window.width * 0.28)
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        ActionButton {
                            text: "‹"
                            enabled: backend.canGoUp
                            Layout.preferredWidth: 52
                            buttonColor: panelRaised
                            onClicked: backend.goUp()
                        }
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                text: "PROGRAMAS"
                                color: textMuted
                                font.pixelSize: 12
                                font.weight: Font.Bold
                                font.letterSpacing: 1.2
                            }
                            Text {
                                text: backend.currentPath || "Inicio"
                                color: textMain
                                font.pixelSize: 17
                                elide: Text.ElideMiddle
                                Layout.fillWidth: true
                            }
                        }
                        ActionButton {
                            text: "↻"
                            Layout.preferredWidth: 52
                            buttonColor: panelRaised
                            onClicked: backend.refresh()
                        }
                    }

                    ListView {
                        id: programList
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        clip: true
                        spacing: 7
                        model: backend.entries

                        delegate: Rectangle {
                            required property var modelData
                            width: programList.width
                            height: 62
                            radius: 12
                            color: itemArea.pressed ? Qt.lighter(panelRaised, 1.12) : panelRaised
                            border.color: modelData.path === backend.document.path ? accent : "transparent"
                            border.width: 1

                            RowLayout {
                                anchors.fill: parent
                                anchors.leftMargin: 14
                                anchors.rightMargin: 14
                                spacing: 12
                                Text {
                                    text: modelData.kind === "directory" ? "▰" : "NC"
                                    color: modelData.kind === "directory" ? accent : textMuted
                                    font.pixelSize: modelData.kind === "directory" ? 22 : 12
                                    font.weight: Font.Bold
                                    Layout.preferredWidth: 30
                                }
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    spacing: 2
                                    Text {
                                        text: modelData.name
                                        color: textMain
                                        font.pixelSize: 16
                                        font.weight: Font.Medium
                                        elide: Text.ElideRight
                                        Layout.fillWidth: true
                                    }
                                    Text {
                                        text: modelData.kind === "directory"
                                              ? "Carpeta"
                                              : Math.max(1, Math.round(modelData.size / 1024)) + " KB"
                                        color: textMuted
                                        font.pixelSize: 12
                                    }
                                }
                                Text {
                                    text: "›"
                                    color: textMuted
                                    font.pixelSize: 25
                                }
                            }
                            TapHandler {
                                id: itemArea
                                onTapped: backend.openEntry(modelData.path, modelData.kind)
                            }
                        }
                    }

                    RowLayout {
                        Layout.fillWidth: true
                        TextField {
                            id: newName
                            Layout.fillWidth: true
                            implicitHeight: 52
                            placeholderText: "Nuevo programa.nc"
                            color: textMain
                            placeholderTextColor: textMuted
                            font.pixelSize: 15
                            background: Rectangle {
                                radius: 13
                                color: panelRaised
                                border.color: newName.activeFocus ? accent : line
                            }
                        }
                        ActionButton {
                            text: "+"
                            Layout.preferredWidth: 52
                            onClicked: {
                                backend.createProgram(newName.text)
                                newName.clear()
                            }
                        }
                    }
                }
            }

            Panel {
                Layout.fillWidth: true
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 10

                    RowLayout {
                        Layout.fillWidth: true
                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Text {
                                text: backend.document.name || "EDITOR CNC"
                                color: textMain
                                font.pixelSize: 19
                                font.weight: Font.DemiBold
                            }
                            Text {
                                text: backend.document.path || "Selecciona un programa"
                                color: textMuted
                                font.pixelSize: 12
                            }
                        }
                        ActionButton {
                            text: "Guardar"
                            enabled: backend.document.path !== undefined && !backend.document.truncated
                            Layout.preferredWidth: 120
                            onClicked: backend.saveDocument(editor.text)
                        }
                    }

                    TextArea {
                        id: editor
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        text: ""
                        readOnly: backend.document.path === undefined || backend.document.truncated
                        color: textMain
                        selectionColor: accent
                        selectedTextColor: "#061014"
                        font.family: "JetBrains Mono"
                        font.pixelSize: 16
                        wrapMode: TextEdit.NoWrap
                        padding: 16
                        background: Rectangle {
                            radius: 14
                            color: "#0A111B"
                            border.color: editor.activeFocus ? accent : line
                        }
                        onTextChanged: {
                            // El binding se rompe al editar; el documento guardado
                            // sigue siendo la referencia para detectar cambios.
                        }
                    }

                    Connections {
                        target: backend
                        function onDocumentChanged() {
                            editor.text = backend.document.content || ""
                        }
                    }
                }
            }

            Panel {
                Layout.preferredWidth: Math.max(245, window.width * 0.22)
                Layout.fillHeight: true

                ColumnLayout {
                    anchors.fill: parent
                    anchors.margins: 14
                    spacing: 12

                    Text {
                        text: "MÁQUINA"
                        color: textMuted
                        font.pixelSize: 12
                        font.weight: Font.Bold
                        font.letterSpacing: 1.2
                    }

                    ListView {
                        id: machineList
                        Layout.fillWidth: true
                        Layout.preferredHeight: Math.min(contentHeight, 250)
                        spacing: 7
                        model: backend.machines

                        delegate: Rectangle {
                            required property var modelData
                            width: machineList.width
                            height: 62
                            radius: 12
                            color: machineArea.pressed ? Qt.lighter(panelRaised, 1.12) : panelRaised
                            border.color: backend.selectedMachineId === modelData.id ? accent : line
                            border.width: backend.selectedMachineId === modelData.id ? 2 : 1
                            Column {
                                anchors.verticalCenter: parent.verticalCenter
                                anchors.left: parent.left
                                anchors.leftMargin: 14
                                width: parent.width - 28
                                spacing: 3
                                Text {
                                    text: modelData.name
                                    color: textMain
                                    font.pixelSize: 16
                                    font.weight: Font.DemiBold
                                }
                                Text {
                                    text: modelData.baudrate + " · "
                                          + modelData.bytesize + modelData.parity + modelData.stopbits
                                    color: textMuted
                                    font.pixelSize: 12
                                }
                            }
                            TapHandler {
                                id: machineArea
                                onTapped: backend.selectMachine(modelData.id)
                            }
                        }
                    }

                    Rectangle {
                        Layout.fillWidth: true
                        Layout.preferredHeight: 1
                        color: line
                    }

                    Text {
                        text: "TRANSFERENCIA"
                        color: textMuted
                        font.pixelSize: 12
                        font.weight: Font.Bold
                        font.letterSpacing: 1.2
                    }

                    Text {
                        Layout.fillWidth: true
                        text: backend.transfer.message || (
                            backend.transfer.status === "sending"
                            ? "Enviando " + backend.transfer.filename
                            : "Lista para enviar"
                        )
                        color: backend.transfer.status === "error" ? danger
                             : backend.transfer.status === "success" ? success
                             : textMain
                        font.pixelSize: 15
                        wrapMode: Text.Wrap
                    }

                    ProgressBar {
                        Layout.fillWidth: true
                        value: (backend.transfer.percent || 0) / 100
                        from: 0
                        to: 1
                        visible: backend.transfer.status === "sending"
                        background: Rectangle { radius: 4; color: line }
                        contentItem: Rectangle { radius: 4; color: accent }
                    }

                    Item { Layout.fillHeight: true }

                    ActionButton {
                        Layout.fillWidth: true
                        text: backend.transfer.status === "sending" ? "CANCELAR" : "ENVIAR"
                        enabled: backend.transfer.status === "sending" || backend.canSend
                        buttonColor: backend.transfer.status === "sending" ? danger : accent
                        onClicked: {
                            if (backend.transfer.status === "sending")
                                backend.cancelTransfer()
                            else
                                backend.sendSelected()
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: settingsDialog
        anchors.centerIn: parent
        width: Math.min(620, window.width - 60)
        height: Math.min(500, window.height - 50)
        modal: true
        title: "Conectar con ZeuzAgent"
        closePolicy: Popup.CloseOnEscape

        onOpened: {
            agentAddress.text = backend.agentUrl || "http://zeuz-agent.local:47820"
            pairingCode.text = ""
        }

        background: Rectangle {
            radius: 18
            color: panel
            border.color: line
        }

        header: Rectangle {
            implicitHeight: 64
            color: "transparent"
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 22
                anchors.verticalCenter: parent.verticalCenter
                text: "CONEXIÓN DE PROGRAMAS"
                color: textMain
                font.pixelSize: 19
                font.weight: Font.Bold
            }
        }

        contentItem: ColumnLayout {
            spacing: 13

            Text {
                text: "ZeuzAgent permite compartir la misma biblioteca con iPhone, Windows, macOS y esta Raspberry."
                color: textMuted
                font.pixelSize: 14
                wrapMode: Text.Wrap
                Layout.fillWidth: true
            }

            Text {
                text: "Dirección del agente"
                color: textMain
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }

            TextField {
                id: agentAddress
                Layout.fillWidth: true
                implicitHeight: 52
                color: textMain
                placeholderText: "http://192.168.1.50:47820"
                placeholderTextColor: textMuted
                font.pixelSize: 16
                inputMethodHints: Qt.ImhUrlCharactersOnly
                background: Rectangle {
                    radius: 12
                    color: panelRaised
                    border.color: agentAddress.activeFocus ? accent : line
                }
            }

            Text {
                text: "Código de seis dígitos"
                color: textMain
                font.pixelSize: 14
                font.weight: Font.DemiBold
            }

            TextField {
                id: pairingCode
                Layout.fillWidth: true
                implicitHeight: 52
                color: textMain
                placeholderText: "000000"
                placeholderTextColor: textMuted
                font.pixelSize: 22
                font.letterSpacing: 5
                maximumLength: 6
                inputMethodHints: Qt.ImhDigitsOnly
                horizontalAlignment: TextInput.AlignHCenter
                background: Rectangle {
                    radius: 12
                    color: panelRaised
                    border.color: pairingCode.activeFocus ? accent : line
                }
            }

            Text {
                Layout.fillWidth: true
                text: backend.status
                color: backend.agentConfigured ? success
                     : backend.status.indexOf("Error") >= 0 ? danger
                     : textMuted
                font.pixelSize: 13
                wrapMode: Text.Wrap
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true

                ActionButton {
                    text: "USAR LOCAL"
                    buttonColor: panelRaised
                    onClicked: backend.useLocalPrograms()
                }

                Item { Layout.fillWidth: true }

                ActionButton {
                    text: "CERRAR"
                    buttonColor: panelRaised
                    onClicked: settingsDialog.close()
                }

                ActionButton {
                    text: backend.busy ? "CONECTANDO…" : "EMPAREJAR"
                    enabled: !backend.busy
                    onClicked: backend.pairAgent(agentAddress.text, pairingCode.text)
                }
            }
        }
    }
}
