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

    function toggleFloatingKeyboard() {
        if (floatingKeyboard.visible) {
            floatingKeyboard.visible = false
        } else if (floatingKeyboard.target) {
            floatingKeyboard.reopen()
        } else {
            floatingKeyboard.showFor(newName, false)
        }
    }

    function applyEditorText(value) {
        var oldCursor = editor.cursorPosition
        editor.text = value
        editor.cursorPosition = Math.min(oldCursor, editor.length)
        editor.forceActiveFocus()
    }

    component Panel: Rectangle {
        radius: 18
        color: window.panel
        border.color: window.line
        border.width: 1
    }

    component ActionButton: Button {
        id: control
        property color buttonColor: window.accent
        readonly property real buttonLuminance: 0.299 * buttonColor.r
                                                + 0.587 * buttonColor.g
                                                + 0.114 * buttonColor.b
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
            color: !control.enabled ? "#708095"
                 : control.buttonLuminance > 0.56 ? "#071118" : window.textMain
            horizontalAlignment: Text.AlignHCenter
            verticalAlignment: Text.AlignVCenter
            font: control.font
            elide: Text.ElideRight
            maximumLineCount: 1
            leftPadding: 7
            rightPadding: 7
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
                elide: Text.ElideRight
                Layout.maximumWidth: 135
            }

            ActionButton {
                text: backend.wifiConnected && backend.wifiIP
                      ? "WI-FI · " + backend.wifiIP : "WI-FI"
                Layout.preferredWidth: 168
                font.pixelSize: 12
                buttonColor: backend.wifiConnected ? success : panelRaised
                onClicked: wifiDialog.open()
            }

            ActionButton {
                text: "TECLADO"
                Layout.preferredWidth: 112
                buttonColor: panelRaised
                onClicked: window.toggleFloatingKeyboard()
            }

            ActionButton {
                text: backend.updateAvailable ? "ACTUALIZAR" : "AJUSTES"
                Layout.preferredWidth: 122
                buttonColor: backend.updateAvailable ? success : panelRaised
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
                            onActiveFocusChanged: {
                                if (activeFocus)
                                    floatingKeyboard.showFor(newName, false)
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
                            text: "EDITAR"
                            enabled: !editor.readOnly
                            Layout.preferredWidth: 108
                            buttonColor: panelRaised
                            onClicked: editorActions.open()
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
                        onActiveFocusChanged: {
                            if (activeFocus && !readOnly)
                                floatingKeyboard.showFor(editor, true)
                        }
                        onTextChanged: {
                            // El binding se rompe al editar; el documento guardado
                            // sigue siendo la referencia para detectar cambios.
                        }
                        Component.onCompleted: backend.attachEditorDocument(editor.textDocument)
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

                    ActionButton {
                        Layout.fillWidth: true
                        text: backend.selectedMachineName || "SELECCIONAR MÁQUINA"
                        buttonColor: backend.selectedMachineId ? success : panelRaised
                        onClicked: machineDialog.open()
                    }

                    Text {
                        Layout.fillWidth: true
                        text: backend.selectedMachineId
                              ? "Perfil listo para la transferencia"
                              : "Selecciona, edita o agrega una máquina"
                        color: backend.selectedMachineId ? success : textMuted
                        font.pixelSize: 12
                        wrapMode: Text.Wrap
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
        id: editorActions
        anchors.centerIn: parent
        width: Math.min(620, window.width - 50)
        height: 360
        modal: true
        title: "Herramientas del editor"
        closePolicy: Popup.CloseOnEscape
        background: Rectangle { radius: 18; color: panel; border.color: line }
        header: Rectangle {
            implicitHeight: 62
            color: "transparent"
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 22
                anchors.verticalCenter: parent.verticalCenter
                text: "HERRAMIENTAS DEL EDITOR"
                color: textMain
                font.pixelSize: 19
                font.weight: Font.Bold
            }
        }
        contentItem: ColumnLayout {
            spacing: 12
            GridLayout {
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 12
                rowSpacing: 12
                ActionButton {
                    Layout.fillWidth: true
                    text: "BUSCAR"
                    buttonColor: panelRaised
                    onClicked: {
                        editorActions.close()
                        searchDialog.replacementMode = false
                        searchDialog.open()
                    }
                }
                ActionButton {
                    Layout.fillWidth: true
                    text: "BUSCAR Y REEMPLAZAR"
                    buttonColor: panelRaised
                    onClicked: {
                        editorActions.close()
                        searchDialog.replacementMode = true
                        searchDialog.open()
                    }
                }
                ActionButton {
                    Layout.fillWidth: true
                    text: "QUITAR NUMERACIÓN N"
                    buttonColor: panelRaised
                    onClicked: {
                        window.applyEditorText(backend.removeLineNumbers(editor.text))
                        editorActions.close()
                    }
                }
                ActionButton {
                    Layout.fillWidth: true
                    text: "AÑADIR NUMERACIÓN N"
                    buttonColor: panelRaised
                    onClicked: {
                        window.applyEditorText(backend.addLineNumbers(editor.text))
                        editorActions.close()
                    }
                }
                ActionButton {
                    Layout.fillWidth: true
                    text: "DESHACER"
                    enabled: editor.canUndo
                    buttonColor: panelRaised
                    onClicked: {
                        editor.undo()
                        editorActions.close()
                    }
                }
                ActionButton {
                    Layout.fillWidth: true
                    text: "CERRAR"
                    buttonColor: panelRaised
                    onClicked: editorActions.close()
                }
            }
            Item { Layout.fillHeight: true }
        }
    }

    Dialog {
        id: searchDialog
        anchors.centerIn: parent
        width: Math.min(650, window.width - 50)
        height: replacementMode ? 360 : 280
        modal: true
        title: replacementMode ? "Buscar y reemplazar" : "Buscar"
        closePolicy: Popup.CloseOnEscape
        property bool replacementMode: false
        property string resultMessage: ""

        function findNext() {
            var query = searchText.text
            if (!query.length) {
                resultMessage = "Escribe el texto que deseas buscar"
                return false
            }
            var position = editor.text.indexOf(query, editor.selectionEnd)
            if (position < 0)
                position = editor.text.indexOf(query, 0)
            if (position < 0) {
                resultMessage = "No se encontró \"" + query + "\""
                return false
            }
            editor.select(position, position + query.length)
            resultMessage = "Coincidencia encontrada"
            return true
        }

        function replaceCurrent() {
            var query = searchText.text
            if (editor.selectedText !== query && !findNext())
                return
            var start = editor.selectionStart
            editor.remove(editor.selectionStart, editor.selectionEnd)
            editor.insert(start, replacementText.text)
            editor.cursorPosition = start + replacementText.text.length
            resultMessage = "Coincidencia reemplazada"
            findNext()
        }

        function replaceEveryMatch() {
            var query = searchText.text
            if (!query.length) {
                resultMessage = "Escribe el texto que deseas buscar"
                return
            }
            var count = editor.text.split(query).length - 1
            if (!count) {
                resultMessage = "No se encontró \"" + query + "\""
                return
            }
            window.applyEditorText(backend.replaceAll(editor.text, query, replacementText.text))
            resultMessage = count + (count === 1 ? " reemplazo" : " reemplazos")
        }

        onOpened: {
            resultMessage = ""
            searchText.forceActiveFocus()
        }
        background: Rectangle { radius: 18; color: panel; border.color: line }
        header: Rectangle {
            implicitHeight: 62
            color: "transparent"
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 22
                anchors.verticalCenter: parent.verticalCenter
                text: searchDialog.replacementMode ? "BUSCAR Y REEMPLAZAR" : "BUSCAR"
                color: textMain
                font.pixelSize: 19
                font.weight: Font.Bold
            }
        }
        contentItem: ColumnLayout {
            spacing: 10
            TextField {
                id: searchText
                Layout.fillWidth: true
                implicitHeight: 48
                color: textMain
                placeholderText: "Texto a buscar"
                placeholderTextColor: textMuted
                background: Rectangle { radius: 10; color: panelRaised; border.color: searchText.activeFocus ? accent : line }
                onActiveFocusChanged: if (activeFocus) floatingKeyboard.showFor(searchText, false)
                onAccepted: searchDialog.findNext()
            }
            TextField {
                id: replacementText
                visible: searchDialog.replacementMode
                Layout.fillWidth: true
                implicitHeight: 48
                color: textMain
                placeholderText: "Reemplazar por"
                placeholderTextColor: textMuted
                background: Rectangle { radius: 10; color: panelRaised; border.color: replacementText.activeFocus ? accent : line }
                onActiveFocusChanged: if (activeFocus) floatingKeyboard.showFor(replacementText, false)
            }
            Text {
                Layout.fillWidth: true
                text: searchDialog.resultMessage
                color: textMuted
                font.pixelSize: 13
            }
            Item { Layout.fillHeight: true }
            RowLayout {
                Layout.fillWidth: true
                ActionButton {
                    text: "CERRAR"
                    buttonColor: panelRaised
                    onClicked: searchDialog.close()
                }
                Item { Layout.fillWidth: true }
                ActionButton {
                    visible: searchDialog.replacementMode
                    text: "REEMPLAZAR TODO"
                    buttonColor: panelRaised
                    onClicked: searchDialog.replaceEveryMatch()
                }
                ActionButton {
                    visible: searchDialog.replacementMode
                    text: "REEMPLAZAR"
                    buttonColor: panelRaised
                    onClicked: searchDialog.replaceCurrent()
                }
                ActionButton {
                    text: "SIGUIENTE"
                    onClicked: searchDialog.findNext()
                }
            }
        }
    }

    Dialog {
        id: wifiDialog
        objectName: "wifiDialog"
        anchors.centerIn: parent
        width: Math.min(720, window.width - 50)
        height: Math.min(540, window.height - 35)
        modal: true
        title: "Configurar Wi-Fi"
        closePolicy: Popup.CloseOnEscape

        onOpened: {
            wifiPassword.text = ""
            backend.refreshWifiStatus()
            backend.scanWifi()
        }

        background: Rectangle {
            radius: 18
            color: panel
            border.color: line
        }

        header: Rectangle {
            implicitHeight: 64
            color: "transparent"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 22
                anchors.rightMargin: 18
                Text {
                    text: "CONFIGURACIÓN WI-FI"
                    color: textMain
                    font.pixelSize: 19
                    font.weight: Font.Bold
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: backend.wifiConnected
                          ? backend.wifiSSID + " · " + backend.wifiIP
                          : "Sin conexión"
                    color: backend.wifiConnected ? success : textMuted
                    font.pixelSize: 12
                    elide: Text.ElideMiddle
                    Layout.maximumWidth: 310
                }
            }
        }

        contentItem: ColumnLayout {
            spacing: 10

            RowLayout {
                Layout.fillWidth: true
                Text {
                    text: "REDES DISPONIBLES"
                    color: textMuted
                    font.pixelSize: 12
                    font.weight: Font.Bold
                    font.letterSpacing: 1.1
                }
                Item { Layout.fillWidth: true }
                ActionButton {
                    text: "BUSCAR"
                    Layout.preferredWidth: 105
                    buttonColor: panelRaised
                    enabled: !backend.busy
                    onClicked: backend.scanWifi()
                }
            }

            ListView {
                id: wifiList
                Layout.fillWidth: true
                Layout.preferredHeight: 190
                clip: true
                spacing: 6
                model: backend.wifiNetworks

                delegate: Rectangle {
                    required property var modelData
                    width: wifiList.width
                    height: 52
                    radius: 11
                    color: wifiNetworkTap.pressed ? Qt.lighter(panelRaised, 1.12) : panelRaised
                    border.color: wifiSsid.text === modelData.ssid ? accent : line
                    border.width: wifiSsid.text === modelData.ssid ? 2 : 1
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        Text {
                            Layout.fillWidth: true
                            text: modelData.ssid
                            color: textMain
                            font.pixelSize: 15
                            font.weight: Font.DemiBold
                            elide: Text.ElideRight
                        }
                        Text {
                            text: modelData.security + " · " + modelData.signal + "%"
                            color: modelData.active ? success : textMuted
                            font.pixelSize: 12
                        }
                    }
                    TapHandler {
                        id: wifiNetworkTap
                        onTapped: {
                            wifiSsid.text = modelData.ssid
                            wifiPassword.forceActiveFocus()
                        }
                    }
                }
            }

            RowLayout {
                Layout.fillWidth: true
                spacing: 10
                TextField {
                    id: wifiSsid
                    Layout.fillWidth: true
                    implicitHeight: 50
                    color: textMain
                    placeholderText: "Nombre de la red"
                    placeholderTextColor: textMuted
                    font.pixelSize: 15
                    background: Rectangle {
                        radius: 11
                        color: panelRaised
                        border.color: wifiSsid.activeFocus ? accent : line
                    }
                    onActiveFocusChanged: if (activeFocus) floatingKeyboard.showFor(wifiSsid, false)
                }
                TextField {
                    id: wifiPassword
                    Layout.fillWidth: true
                    implicitHeight: 50
                    color: textMain
                    placeholderText: "Contraseña (vacía si es abierta)"
                    placeholderTextColor: textMuted
                    font.pixelSize: 15
                    echoMode: TextInput.Password
                    background: Rectangle {
                        radius: 11
                        color: panelRaised
                        border.color: wifiPassword.activeFocus ? accent : line
                    }
                    onActiveFocusChanged: if (activeFocus) floatingKeyboard.showFor(wifiPassword, false)
                }
            }

            Text {
                Layout.fillWidth: true
                text: backend.status
                color: backend.wifiConnected ? success : textMuted
                font.pixelSize: 13
                wrapMode: Text.Wrap
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton {
                    text: "CERRAR"
                    buttonColor: panelRaised
                    onClicked: wifiDialog.close()
                }
                ActionButton {
                    text: backend.busy ? "CONECTANDO…" : "CONECTAR"
                    enabled: !backend.busy && wifiSsid.text.trim().length > 0
                    onClicked: backend.connectWifi(wifiSsid.text, wifiPassword.text)
                }
            }
        }
    }

    Dialog {
        id: machineDialog
        objectName: "machineDialog"
        anchors.centerIn: parent
        width: Math.min(720, window.width - 50)
        height: Math.min(520, window.height - 40)
        modal: true
        title: "Máquinas"
        closePolicy: Popup.CloseOnEscape

        background: Rectangle { radius: 18; color: panel; border.color: line }
        header: Rectangle {
            implicitHeight: 64
            color: "transparent"
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 22
                anchors.rightMargin: 18
                Text {
                    text: "SELECCIONAR MÁQUINA"
                    color: textMain
                    font.pixelSize: 19
                    font.weight: Font.Bold
                }
                Item { Layout.fillWidth: true }
                ActionButton {
                    text: "+"
                    Layout.preferredWidth: 52
                    onClicked: {
                        machineDialog.close()
                        machineEditor.openFor(null)
                    }
                }
            }
        }

        contentItem: ColumnLayout {
            spacing: 10
            ListView {
                id: machineSelectorList
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                spacing: 8
                model: backend.machines

                delegate: RowLayout {
                    required property var modelData
                    width: machineSelectorList.width
                    height: 62
                    spacing: 8
                    ActionButton {
                        Layout.fillWidth: true
                        text: modelData.name + "  ·  " + modelData.baudrate + "  "
                              + modelData.bytesize + modelData.parity + modelData.stopbits
                        buttonColor: backend.selectedMachineId === modelData.id
                                     ? success : panelRaised
                        onClicked: {
                            backend.selectMachine(modelData.id)
                            machineDialog.close()
                        }
                    }
                    ActionButton {
                        text: "EDITAR"
                        Layout.preferredWidth: 105
                        buttonColor: panelRaised
                        onClicked: {
                            machineDialog.close()
                            machineEditor.openFor(modelData)
                        }
                    }
                }
            }
            Text {
                visible: backend.machines.length === 0
                Layout.fillWidth: true
                text: "No hay máquinas. Pulsa + para crear la primera."
                color: textMuted
                horizontalAlignment: Text.AlignHCenter
                font.pixelSize: 15
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton {
                    text: "CERRAR"
                    buttonColor: panelRaised
                    onClicked: machineDialog.close()
                }
            }
        }
    }

    Dialog {
        id: machineEditor
        objectName: "machineEditor"
        anchors.centerIn: parent
        width: Math.min(820, window.width - 35)
        height: Math.min(560, window.height - 24)
        modal: true
        title: editingId ? "Editar máquina" : "Nueva máquina"
        closePolicy: Popup.CloseOnEscape
        property string editingId: ""

        function choose(combo, value) {
            for (var index = 0; index < combo.count; ++index) {
                if (String(combo.model[index]) === String(value)) {
                    combo.currentIndex = index
                    return
                }
            }
            combo.currentIndex = 0
        }

        function openFor(machine) {
            editingId = machine ? machine.id : ""
            machineName.text = machine ? machine.name : ""
            choose(machineBaud, machine ? machine.baudrate : 9600)
            choose(machineBytes, machine ? machine.bytesize : 8)
            choose(machineParity, machine ? machine.parity : "N")
            choose(machineStop, machine ? machine.stopbits : 1)
            choose(machineFlow, machine ? machine.flow_control : "none")
            choose(machineTerminator, machine ? machine.line_terminator : "CRLF")
            machineDtr.checked = machine ? Boolean(machine.dtr) : false
            machineRts.checked = machine ? Boolean(machine.rts) : false
            machineDripfeed.checked = machine ? Boolean(machine.dripfeed) : false
            open()
        }

        background: Rectangle { radius: 18; color: panel; border.color: line }
        header: Rectangle {
            implicitHeight: 62
            color: "transparent"
            Text {
                anchors.left: parent.left
                anchors.leftMargin: 22
                anchors.verticalCenter: parent.verticalCenter
                text: machineEditor.editingId ? "EDITAR MÁQUINA" : "NUEVA MÁQUINA"
                color: textMain
                font.pixelSize: 19
                font.weight: Font.Bold
            }
        }

        contentItem: ColumnLayout {
            spacing: 12

            GridLayout {
                Layout.fillWidth: true
                columns: 4
                columnSpacing: 12
                rowSpacing: 9

                Text { text: "Nombre"; color: textMain; font.pixelSize: 13 }
                TextField {
                    id: machineName
                    Layout.fillWidth: true
                    implicitHeight: 46
                    color: textMain
                    placeholderText: "Centro de maquinado 1"
                    placeholderTextColor: textMuted
                    background: Rectangle { radius: 10; color: panelRaised; border.color: machineName.activeFocus ? accent : line }
                    onActiveFocusChanged: if (activeFocus) floatingKeyboard.showFor(machineName, false)
                }
                Text { text: "Baudrate"; color: textMain; font.pixelSize: 13 }
                ComboBox {
                    id: machineBaud
                    Layout.fillWidth: true
                    implicitHeight: 46
                    model: [110, 300, 600, 1200, 2400, 4800, 9600, 14400,
                            19200, 38400, 57600, 115200, 128000, 256000]
                }

                Text { text: "Bits de datos"; color: textMain; font.pixelSize: 13 }
                ComboBox { id: machineBytes; Layout.fillWidth: true; model: [5, 6, 7, 8] }
                Text { text: "Paridad"; color: textMain; font.pixelSize: 13 }
                ComboBox { id: machineParity; Layout.fillWidth: true; model: ["N", "E", "O", "M", "S"] }

                Text { text: "Bits de parada"; color: textMain; font.pixelSize: 13 }
                ComboBox { id: machineStop; Layout.fillWidth: true; model: [1, 2] }
                Text { text: "Control de flujo"; color: textMain; font.pixelSize: 13 }
                ComboBox { id: machineFlow; Layout.fillWidth: true; model: ["none", "xonxoff", "rtscts"] }

                Text { text: "Terminador"; color: textMain; font.pixelSize: 13 }
                ComboBox { id: machineTerminator; Layout.fillWidth: true; model: ["CR", "CRLF", "LF"] }
                Text { text: "Señales"; color: textMain; font.pixelSize: 13 }
                RowLayout {
                    CheckBox { id: machineDtr; text: "DTR"; palette.windowText: textMain }
                    CheckBox { id: machineRts; text: "RTS"; palette.windowText: textMain }
                    CheckBox { id: machineDripfeed; text: "Drip feed"; palette.windowText: textMain }
                }
            }

            Text {
                Layout.fillWidth: true
                text: backend.status
                color: textMuted
                font.pixelSize: 13
                wrapMode: Text.Wrap
            }

            Item { Layout.fillHeight: true }

            RowLayout {
                Layout.fillWidth: true
                ActionButton {
                    visible: machineEditor.editingId.length > 0
                    text: "ELIMINAR"
                    buttonColor: danger
                    onClicked: machineDeleteConfirm.open()
                }
                Item { Layout.fillWidth: true }
                ActionButton {
                    text: "CANCELAR"
                    buttonColor: panelRaised
                    onClicked: machineEditor.close()
                }
                ActionButton {
                    text: "GUARDAR"
                    onClicked: {
                        var ok = backend.saveMachine({
                            "id": machineEditor.editingId,
                            "name": machineName.text,
                            "baudrate": parseInt(machineBaud.currentText),
                            "bytesize": parseInt(machineBytes.currentText),
                            "parity": machineParity.currentText,
                            "stopbits": parseInt(machineStop.currentText),
                            "flow_control": machineFlow.currentText,
                            "line_terminator": machineTerminator.currentText,
                            "dtr": machineDtr.checked,
                            "rts": machineRts.checked,
                            "dripfeed": machineDripfeed.checked
                        })
                        if (ok)
                            machineEditor.close()
                    }
                }
            }
        }
    }

    Dialog {
        id: machineDeleteConfirm
        anchors.centerIn: parent
        width: 440
        modal: true
        title: "Eliminar máquina"
        background: Rectangle { radius: 16; color: panel; border.color: line }
        contentItem: ColumnLayout {
            spacing: 16
            Text {
                Layout.fillWidth: true
                text: "¿Eliminar este perfil de máquina?"
                color: textMain
                font.pixelSize: 16
                wrapMode: Text.Wrap
            }
            RowLayout {
                Layout.fillWidth: true
                Item { Layout.fillWidth: true }
                ActionButton { text: "CANCELAR"; buttonColor: panelRaised; onClicked: machineDeleteConfirm.close() }
                ActionButton {
                    text: "ELIMINAR"
                    buttonColor: danger
                    onClicked: {
                        if (backend.deleteMachine(machineEditor.editingId)) {
                            machineDeleteConfirm.close()
                            machineEditor.close()
                        }
                    }
                }
            }
        }
    }

    Dialog {
        id: settingsDialog
        objectName: "settingsDialog"
        anchors.centerIn: parent
        width: Math.min(620, window.width - 60)
        height: Math.min(560, window.height - 30)
        modal: true
        title: "Ajustes"
        closePolicy: Popup.CloseOnEscape

        onOpened: {
            agentAddress.text = backend.agentUrl || "http://zeuz-agent.local:47820"
            pairingCode.text = ""
            backend.refreshUpdateState()
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
                text: "CONEXIÓN Y SISTEMA"
                color: textMain
                font.pixelSize: 19
                font.weight: Font.Bold
            }
        }

        contentItem: ColumnLayout {
            spacing: 13

            Text {
                text: "ZeuzAgent permite compartir la misma biblioteca con iPhone, Windows, macOS y este dispositivo Zeuz."
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
                onActiveFocusChanged: {
                    if (activeFocus)
                        floatingKeyboard.showFor(agentAddress, false)
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
                onActiveFocusChanged: {
                    if (activeFocus)
                        floatingKeyboard.showFor(pairingCode, false)
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

            Rectangle {
                Layout.fillWidth: true
                Layout.preferredHeight: 78
                radius: 12
                color: panelRaised
                border.color: backend.updateAvailable ? success : line
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 12
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 2
                        Text {
                            text: backend.updateAvailable
                                  ? "ACTUALIZACIÓN " + backend.updateVersion + " DISPONIBLE"
                                  : "SISTEMA ZEUZ DNC"
                            color: backend.updateAvailable ? success : textMain
                            font.pixelSize: 14
                            font.weight: Font.Bold
                        }
                        Text {
                            text: backend.updateAvailable
                                  ? "Revisión " + backend.updateRevision
                                  : backend.updateError || ("Versión instalada: " + backend.version)
                            color: backend.updateError ? danger : textMuted
                            font.pixelSize: 12
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                    ActionButton {
                        text: backend.updateAvailable ? "ACTUALIZAR" : "BUSCAR"
                        Layout.preferredWidth: 120
                        buttonColor: backend.updateAvailable ? success : panel
                        enabled: !backend.busy
                        onClicked: {
                            if (backend.updateAvailable)
                                backend.installUpdate()
                            else
                                backend.checkUpdates()
                        }
                    }
                }
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

    FloatingKeyboard {
        id: floatingKeyboard
        objectName: "floatingKeyboard"
        parent: Overlay.overlay
        panelColor: window.panel
        keyColor: window.panelRaised
        borderColor: window.line
        textColor: window.textMain
        mutedTextColor: window.textMuted
        accentColor: window.accent
    }
}
