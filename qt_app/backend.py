from __future__ import annotations

import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, Property, QTimer, Signal, Slot

import serial_transfer
from machines import get_machine, load_machines
from state import state
from zeuz_core.pair_agent import pair, write_local_runtime, write_runtime
from zeuz_core.programs import AgentProgramRepository
from zeuz_core.settings import DEFAULT_SETTINGS_PATH, RuntimeSettings


class AppBackend(QObject):
    entriesChanged = Signal()
    pathChanged = Signal()
    documentChanged = Signal()
    machinesChanged = Signal()
    selectionChanged = Signal()
    statusChanged = Signal()
    transferChanged = Signal()
    sourceChanged = Signal()
    _asyncDone = Signal(object, object, bool)

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
        self._status = "Cargando programas…"
        self._busy = False
        self._transfer = state.snapshot()["transfer"]
        self._temporary_send_file: Path | None = None
        self._active_device = state.snapshot()["active_device"]

        self._asyncDone.connect(self._handle_async_result)
        self._timer = QTimer(self)
        self._timer.setInterval(200)
        self._timer.timeout.connect(self._poll_transfer)
        self._timer.start()
        QTimer.singleShot(0, self.refresh)

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

    @Slot()
    def refresh(self) -> None:
        path = self._path

        def loaded(value: object) -> None:
            listing = value
            self._entries = listing["entries"]
            self._path = listing["path"]
            self._parent = listing["parent"]
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
        self.sourceChanged.emit()
        self.pathChanged.emit()
        self.entriesChanged.emit()
        self.documentChanged.emit()
        self.selectionChanged.emit()
        self.refresh()

    @Slot(str)
    def selectMachine(self, machine_id: str) -> None:
        if not get_machine(machine_id):
            return
        self._selected_machine_id = machine_id
        state.select_machine(machine_id)
        self.selectionChanged.emit()

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
