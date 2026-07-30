from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtCore import QUrl
from PySide6.QtGui import QGuiApplication
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle

import usb_monitor
from qt_app.backend import AppBackend


def main() -> int:
    # La interfaz define todos sus controles; Basic evita que el estilo nativo
    # de Windows/macOS ignore fondos, colores y estados personalizados.
    QQuickStyle.setStyle("Basic")
    app = QGuiApplication(sys.argv)
    app.setOrganizationName("Zeuz")
    app.setApplicationName("Zeuz DNC")

    usb_monitor.start_usb_monitor()
    backend = AppBackend()
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    qml_path = Path(__file__).resolve().parent / "qml" / "Main.qml"
    engine.load(QUrl.fromLocalFile(str(qml_path)))
    if not engine.rootObjects():
        return 1
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
