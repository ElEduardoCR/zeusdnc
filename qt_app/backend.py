from __future__ import annotations

import os
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

import serial_transfer
from machines import delete_machine, get_machine, load_machines, save_machine
from state import state
from zeuz_core.pair_agent import pair, write_local_runtime, write_runtime
from zeuz_core.network import WifiManager
from zeuz_core.programs import AgentProgramRepository
from zeuz_core.settings import DEFAULT_SETTINGS_PATH, RuntimeSettings
from zeuz_core.updater import prepare_update, read_update_state, safe_check_for_update
from zeuz_core.version import installed_version
from qt_app.gcode_edit import add_line_numbers, remove_line_numbers, replace_all
from qt_app.highlighter import GCodeSyntaxHighlighter


class AppBackend(QObject):
    entriesChanged = Signal()
    pathChanged = Signal()
    documentChanged = Signal()
    machinesChanged = Signal()
    selectionChanged = Signal()
    statusChanged = Signal()
    transferChanged = Signal()
    sourceChanged = Signal()
    wifiChanged = Signal()
    updateChanged = Signal()
    _asyncDone = Signal(object, object, bool)
    _silentAsyncDone = Signal(object, object, bool)

    def __init__(self) -> None:
        super().__init__()
        self._executor = ThreadPoolExecutor(max_workers=4, thread_name_prefix="zeuz-io")
        self._settings = RuntimeSettings.load()
        try:
            self._repository = self._settings.repository()
        except (OSError, ValueError):
            self._settings = RuntimeSettings(source_type="local")
            self._repository = self._settings.repository()
        self._entries: list[dict] = []
        self._path = ""
        self._parent: str | None = None
        self._document: dict = {}
        self._machines = load_machines()
        self._selected_machine_id = ""
        self._wifi = WifiManager()
        self._wifi_networks: list[dict] = []
        self._wifi_status = {"connected": False, "ssid": "", "ip": "", "interface": "wlan0"}
        self._update_state = read_update_state()
        self._status = "Cargando programas…"
        self._busy = False
        self._transfer = state.snapshot()["transfer"]
        self._temporary_send_file: Path | None = None
        self._active_device = state.snapshot()["active_device"]
        self._program_refresh_in_flight = False
        self._has_loaded_programs = False
        self._highlighter: GCodeSyntaxHighlighter | None = None

        self._asyncDone.connect(self._handle_async_result)
        self._silentAsyncDone.connect(self._handle_silent_async_result)
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll_transfer)
        self._timer.start()
        self._update_timer = QTimer(self)
        self._update_timer.setInterval(3000)
        self._update_timer.timeout.connect(self.refreshUpdateState)
        self._update_timer.start()
        self._program_timer = QTimer(self)
        self._program_timer.setInterval(5000)
        self._program_timer.timeout.connect(self.autoRefreshPrograms)
        self._program_timer.start()
        QTimer.singleShot(0, self.refresh)
        QTimer.singleShot(500, self.refreshWifiStatus)
        QTimer.singleShot(2000, self.autoRefreshPrograms)
        QTimer.singleShot(5000, self.autoRefreshPrograms)

    @Property("QVariantList", notify=entriesChanged)
    def entries(self) -> list[dict]:
        return self._entries

    @Property(str, notify=pathChanged)
    def currentPath(self) -> str:
        return self._path

    @Property(bool, notify=pathChanged)
    def canGoUp(self) -> bool:
        return self._parent is not None

    @Property("QVariantMap", notify=documentChanged)
    def document(self) -> dict:
        return self._document

    @Property("QVariantList", notify=machinesChanged)
    def machines(self) -> list[dict]:
        return self._machines

    @Property(str, notify=selectionChanged)
    def selectedMachineId(self) -> str:
        return self._selected_machine_id

    @Property(str, notify=selectionChanged)
    def selectedMachineName(self) -> str:
        machine = next(
            (item for item in self._machines if item.get("id") == self._selected_machine_id),
            None,
        )
        return str(machine.get("name", "")) if machine else ""

    @Property(str, notify=statusChanged)
    def status(self) -> str:
        return self._status

    @Property(bool, notify=statusChanged)
    def busy(self) -> bool:
        return self._busy

    @Property("QVariantMap", notify=transferChanged)
    def transfer(self) -> dict:
        return self._transfer

    @Property(bool, notify=selectionChanged)
    def canSend(self) -> bool:
        snap = state.snapshot()
        return bool(
            self._document
            and self._selected_machine_id
            and snap["active_device"]
            and snap["transfer"]["status"] != "sending"
        )

    @Property(str, notify=sourceChanged)
    def sourceType(self) -> str:
        return self._settings.source_type

    @Property(str, notify=sourceChanged)
    def sourceLabel(self) -> str:
        if self._settings.source_type == "agent":
            return "ZeuzAgent"
        return "Programas locales"

    @Property(str, notify=sourceChanged)
    def agentUrl(self) -> str:
        return self._settings.agent_url

    @Property(bool, notify=sourceChanged)
    def agentConfigured(self) -> bool:
        return self._settings.source_type == "agent" and bool(self._settings.agent_token)

    @Property("QVariantList", notify=wifiChanged)
    def wifiNetworks(self) -> list[dict]:
        return self._wifi_networks

    @Property(bool, notify=wifiChanged)
    def wifiConnected(self) -> bool:
        return bool(self._wifi_status.get("connected"))

    @Property(str, notify=wifiChanged)
    def wifiSSID(self) -> str:
        return str(self._wifi_status.get("ssid", ""))

    @Property(str, notify=wifiChanged)
    def wifiIP(self) -> str:
        return str(self._wifi_status.get("ip", ""))

    @Property(bool, notify=updateChanged)
    def updateAvailable(self) -> bool:
        return bool(self._update_state.get("available"))

    @Property(str, notify=updateChanged)
    def updateVersion(self) -> str:
        return str(self._update_state.get("latest_version", ""))

    @Property(str, notify=updateChanged)
    def updateRevision(self) -> str:
        return str(self._update_state.get("latest_revision", ""))[:8]

    @Property(str, notify=updateChanged)
    def updateError(self) -> str:
        return str(self._update_state.get("error", ""))

    @Property(str, constant=True)
    def version(self) -> str:
        return installed_version()

    def _set_status(self, message: str, busy: bool | None = None) -> None:
        self._status = message
        if busy is not None:
            self._busy = busy
        self.statusChanged.emit()

    def _submit(
        self,
        work: Callable[[], object],
        success: Callable[[object], None],
        activity: str,
    ) -> None:
        self._set_status(activity, True)
        future = self._executor.submit(work)

        def completed(done) -> None:
            try:
                result = done.result()
            except Exception as exc:  # noqa: BLE001 - se presenta al operador
                self._asyncDone.emit(success, exc, False)
                return
            self._asyncDone.emit(success, result, True)

        future.add_done_callback(completed)

    @Slot(object, object, bool)
    def _handle_async_result(
        self,
        success: Callable[[object], None],
        result: object,
        ok: bool,
    ) -> None:
        if not ok:
            self._set_status(str(result), False)
            return
        self._set_status("Listo", False)
        success(result)

    def _submit_silent(
        self,
        work: Callable[[], object],
        success: Callable[[object], None],
    ) -> None:
        future = self._executor.submit(work)

        def completed(done) -> None:
            try:
                result = done.result()
            except Exception as exc:  # noqa: BLE001 - silent background retry
                self._silentAsyncDone.emit(success, exc, False)
                return
            self._silentAsyncDone.emit(success, result, True)

        future.add_done_callback(completed)

    @Slot(object, object, bool)
    def _handle_silent_async_result(
        self,
        success: Callable[[object], None],
        result: object,
        ok: bool,
    ) -> None:
        self._program_refresh_in_flight = False
        if ok:
            success(result)

    @Slot()
    def autoRefreshPrograms(self) -> None:
        if self._program_refresh_in_flight or self._busy:
            return
        path = self._path
        repository = self._repository
        self._program_refresh_in_flight = True

        def loaded(value: object) -> None:
            # Ignore an old request if pairing or navigation changed the source.
            if repository is not self._repository or path != self._path:
                return
            listing = value
            entries_changed = listing["entries"] != self._entries
            path_changed = listing["path"] != self._path or listing["parent"] != self._parent
            self._entries = listing["entries"]
            self._path = listing["path"]
            self._parent = listing["parent"]
            first_success = not self._has_loaded_programs
            self._has_loaded_programs = True
            if entries_changed:
                self.entriesChanged.emit()
            if path_changed:
                self.pathChanged.emit()
            if first_success:
                self._set_status("Listo", False)

        self._submit_silent(lambda: repository.list(path), loaded)

    @Slot(QObject)
    def attachEditorDocument(self, quick_document: QObject) -> None:
        text_document = getattr(quick_document, "textDocument", None)
        if callable(text_document):
            text_document = text_document()
        if text_document is not None:
            self._highlighter = GCodeSyntaxHighlighter(text_document)

    @Slot(str, result=str)
    def removeLineNumbers(self, content: str) -> str:
        return remove_line_numbers(content)

    @Slot(str, result=str)
    def addLineNumbers(self, content: str) -> str:
        return add_line_numbers(content)

    @Slot(str, str, str, result=str)
    def replaceAll(self, content: str, search: str, replacement: str) -> str:
        return replace_all(content, search, replacement)

    @Slot()
    def refresh(self) -> None:
        path = self._path

        def loaded(value: object) -> None:
            listing = value
            self._entries = listing["entries"]
            self._path = listing["path"]
            self._parent = listing["parent"]
            self._has_loaded_programs = True
            self.entriesChanged.emit()
            self.pathChanged.emit()

        self._submit(lambda: self._repository.list(path), loaded, "Actualizando programas…")

    @Slot()
    def goUp(self) -> None:
        if self._parent is None:
            return
        target = self._parent
        self._load_directory(target)

    def _load_directory(self, path: str) -> None:
        def loaded(value: object) -> None:
            listing = value
            self._entries = listing["entries"]
            self._path = listing["path"]
            self._parent = listing["parent"]
            self.entriesChanged.emit()
            self.pathChanged.emit()

        self._submit(lambda: self._repository.list(path), loaded, "Abriendo carpeta…")

    @Slot(str, str)
    def openEntry(self, path: str, kind: str) -> None:
        if kind == "directory":
            self._load_directory(path)
            return

        def opened(value: object) -> None:
            self._document = value
            self.documentChanged.emit()
            self.selectionChanged.emit()

        self._submit(lambda: self._repository.read(path), opened, "Abriendo programa…")

    @Slot(str)
    def saveDocument(self, content: str) -> None:
        if not self._document or self._document.get("truncated"):
            return
        path = self._document["path"]
        modified = self._document.get("modified")

        def saved(value: object) -> None:
            result = value
            self._document["content"] = content
            self._document["modified"] = result.get("modified", modified)
            self.documentChanged.emit()
            self.refresh()

        self._submit(
            lambda: self._repository.write(path, content, modified),
            saved,
            "Guardando programa…",
        )

    @Slot(str)
    def createProgram(self, name: str) -> None:
        clean = name.strip()
        if not clean:
            self._set_status("Escribe un nombre para el programa")
            return

        def created(value: object) -> None:
            result = value
            self.refresh()
            self.openEntry(result["path"], "file")

        self._submit(
            lambda: self._repository.create(self._path, clean),
            created,
            "Creando programa…",
        )

    @Slot(str, str)
    def pairAgent(self, base_url: str, code: str) -> None:
        url = base_url.strip().rstrip("/")
        clean_code = code.strip().replace(" ", "")
        if not url.startswith(("http://", "https://")):
            self._set_status("La dirección debe comenzar con http://")
            return
        if len(clean_code) != 6 or not clean_code.isdigit():
            self._set_status("El código debe contener seis dígitos")
            return

        def connect() -> RuntimeSettings:
            result = pair(url, clean_code)
            write_runtime(DEFAULT_SETTINGS_PATH, url, result["token"])
            settings = RuntimeSettings.load()
            settings.repository().list("")
            return settings

        def connected(value: object) -> None:
            self._settings = value
            self._repository = self._settings.repository()
            self._path = ""
            self._parent = None
            self._entries = []
            self._document = {}
            self._has_loaded_programs = False
            self.sourceChanged.emit()
            self.pathChanged.emit()
            self.entriesChanged.emit()
            self.documentChanged.emit()
            self.selectionChanged.emit()
            self.refresh()

        self._submit(connect, connected, "Emparejando con ZeuzAgent…")

    @Slot()
    def useLocalPrograms(self) -> None:
        try:
            write_local_runtime(DEFAULT_SETTINGS_PATH)
            settings = RuntimeSettings.load()
            repository = settings.repository()
        except OSError as exc:
            self._set_status(str(exc))
            return
        self._settings = settings
        self._repository = repository
        self._path = ""
        self._parent = None
        self._entries = []
        self._document = {}
        self._has_loaded_programs = False
        self.sourceChanged.emit()
        self.pathChanged.emit()
        self.entriesChanged.emit()
        self.documentChanged.emit()
        self.selectionChanged.emit()
        self.refresh()

    def _set_wifi_status(self, value: object) -> None:
        self._wifi_status = dict(value)
        self.wifiChanged.emit()
        if self.wifiConnected:
            QTimer.singleShot(0, self.autoRefreshPrograms)

    @Slot()
    def refreshWifiStatus(self) -> None:
        self._submit(self._wifi.status, self._set_wifi_status, "Consultando Wi-Fi…")

    @Slot()
    def scanWifi(self) -> None:
        def scanned(value: object) -> None:
            self._wifi_networks = list(value)
            self.wifiChanged.emit()

        self._submit(self._wifi.scan, scanned, "Buscando redes Wi-Fi…")

    @Slot(str, str)
    def connectWifi(self, ssid: str, password: str) -> None:
        def connected(value: object) -> None:
            self._set_wifi_status(value)
            self._set_status(f"Wi-Fi listo · IP {self.wifiIP}", False)

        self._submit(
            lambda: self._wifi.connect(ssid, password),
            connected,
            f"Conectando a {ssid.strip()}…",
        )

    @Slot()
    def refreshUpdateState(self) -> None:
        value = read_update_state()
        if value != self._update_state:
            self._update_state = value
            self.updateChanged.emit()

    @Slot()
    def checkUpdates(self) -> None:
        def checked(value: object) -> None:
            self._update_state = dict(value)
            self.updateChanged.emit()
            if self.updateAvailable:
                self._set_status(f"Actualización {self.updateVersion} disponible", False)
            elif self.updateError:
                self._set_status(f"No se pudo comprobar: {self.updateError}", False)
            else:
                self._set_status("El sistema está actualizado", False)

        self._submit(safe_check_for_update, checked, "Buscando actualizaciones…")

    @Slot()
    def installUpdate(self) -> None:
        def install() -> object:
            update = prepare_update()
            result = subprocess.run(
                ["sudo", "-n", "/usr/bin/systemctl", "start", "zeuz-update-apply.service"],
                text=True,
                capture_output=True,
                timeout=180,
                check=False,
            )
            if result.returncode != 0:
                detail = (result.stderr or result.stdout or "No se pudo iniciar la actualización")
                raise RuntimeError(detail.strip()[:300])
            return update

        def installed(_value: object) -> None:
            self._set_status("Actualización instalada; reiniciando interfaz…", False)

        self._submit(install, installed, "Descargando e instalando actualización…")

    @Slot(str)
    def selectMachine(self, machine_id: str) -> None:
        if not get_machine(machine_id):
            return
        self._selected_machine_id = machine_id
        state.select_machine(machine_id)
        self.selectionChanged.emit()

    @Slot("QVariantMap", result=bool)
    def saveMachine(self, data: dict) -> bool:
        machine, error = save_machine(dict(data))
        if error or not machine:
            self._set_status(error or "No se pudo guardar la máquina")
            return False
        self._machines = load_machines()
        self._selected_machine_id = machine["id"]
        state.select_machine(machine["id"])
        self.machinesChanged.emit()
        self.selectionChanged.emit()
        self._set_status(f"Máquina {machine['name']} guardada")
        return True

    @Slot(str, result=bool)
    def deleteMachine(self, machine_id: str) -> bool:
        ok, error = delete_machine(machine_id)
        if not ok:
            self._set_status(error or "No se pudo eliminar la máquina")
            return False
        self._machines = load_machines()
        if self._selected_machine_id == machine_id:
            self._selected_machine_id = ""
            state.clear_machine()
        self.machinesChanged.emit()
        self.selectionChanged.emit()
        self._set_status("Máquina eliminada")
        return True

    @Slot()
    def sendSelected(self) -> None:
        if not self._document or not self._selected_machine_id:
            return
        snap = state.snapshot()
        if not snap["active_device"]:
            self._set_status("Conecta y selecciona un puerto RS232")
            return
        profile = get_machine(self._selected_machine_id)
        if not profile:
            self._set_status("Perfil de máquina no encontrado")
            return
        path = self._document["path"]

        def materialized(value: object) -> None:
            send_path = Path(value)
            if isinstance(self._repository, AgentProgramRepository):
                self._temporary_send_file = send_path
            state.reset_transfer()
            ok, error = serial_transfer.start_transfer(
                snap["active_device"],
                profile,
                str(send_path),
                self._document["name"],
            )
            if not ok:
                self._set_status(error or "No se pudo iniciar el envío")

        self._submit(
            lambda: self._repository.materialize(path),
            materialized,
            "Preparando transferencia…",
        )

    @Slot()
    def cancelTransfer(self) -> None:
        serial_transfer.request_cancel()

    def _poll_transfer(self) -> None:
        snap = state.snapshot()
        current = snap["transfer"]
        if snap["active_device"] != self._active_device:
            self._active_device = snap["active_device"]
            self.selectionChanged.emit()
        if current != self._transfer:
            self._transfer = current
            self.transferChanged.emit()
            self.selectionChanged.emit()
            if current["status"] not in {"idle", "sending"} and self._temporary_send_file:
                try:
                    os.unlink(self._temporary_send_file)
                except OSError:
                    pass
                self._temporary_send_file = None
