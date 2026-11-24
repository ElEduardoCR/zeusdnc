from __future__ import annotations

import json
import hashlib
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import serial_transfer
import usb_monitor
from machines import delete_machine, get_machine, load_machines, save_machine, validate_machine
from state import state
from zeuz_core.pair_agent import pair, write_runtime
from zeuz_core.settings import DEFAULT_SETTINGS_PATH, RuntimeSettings
from zeuz_core import workshop, update_auth, remote_updates, system_management
from zeuz_core.updater import read_update_state
from zeuz_core.version import installed_version


def device_identity() -> str | None:
    """Prefer board identity over a potentially cloned OS image; no writes."""
    for filename in ("/proc/device-tree/serial-number", "/sys/devices/soc0/serial_number", "/etc/machine-id"):
        try:
            value = Path(filename).read_text().strip("\x00 \r\n")
        except OSError:
            continue
        if value and set(value) != {"0"}:
            return hashlib.sha256(("zeuz-device:" + filename + ":" + value).encode()).hexdigest()
    return None


class HeadlessController:
    @staticmethod
    def info() -> dict:
        settings = RuntimeSettings.load()
        return {
            "ok": True,
            "service": "zeuz-dnc",
            "device_id": device_identity(),
            "hostname": os.uname().nodename,
            "name": workshop.settings().get("name", os.uname().nodename),
            "version": installed_version(),
            "api": 1,
            "capabilities": {"remote_update": 1, "clock_sync": 1, "transfer_diagnostics": 1},
            "update_paired": bool(update_auth.paired_token()),
            "update": {k: v for k, v in read_update_state().items() if k in {"available", "current_version", "latest_version", "phase", "error"}},
            "agent_configured": settings.source_type == "agent" and bool(settings.agent_token),
        }

    @staticmethod
    def pair_agent(url: str, code: str, management_only: bool = False) -> dict:
        clean_url = str(url or "").strip().rstrip("/")
        clean_code = "".join(character for character in str(code or "") if character.isdigit())
        if not clean_url.startswith(("http://", "https://")):
            raise ValueError("La dirección de Zeuz Agent no es válida")
        if len(clean_code) != 6:
            raise ValueError("El código de Zeuz Agent debe tener seis dígitos")
        result = pair(clean_url, clean_code)
        if management_only:
            from zeuz_core.updater import _atomic_write
            try: value = json.loads(DEFAULT_SETTINGS_PATH.read_text())
            except FileNotFoundError: value = {}
            value["paired_agent"] = {"url": clean_url, "token": result["token"]}
            _atomic_write(DEFAULT_SETTINGS_PATH, json.dumps(value).encode())
        else:
            write_runtime(DEFAULT_SETTINGS_PATH, clean_url, result["token"])
            RuntimeSettings.load().repository().list("")
        return {"ok": True, "agent_name": result.get("agent_name", "Zeuz Agent")}

    def send(self, path: str, supplied_profile: dict | None = None) -> str | None:
        snap = state.snapshot()
        if not snap["usb_devices"]:
            raise Conflict("Cable RS232 no conectado")
        if not supplied_profile and not snap["active_machine_id"]:
            raise Conflict("Selecciona una máquina antes de enviar")
        if snap["transfer"]["status"] == "sending":
            raise Conflict("Ya hay una transferencia en curso")

        profile = None
        if supplied_profile:
            clean, error = validate_machine(supplied_profile)
            if error:
                raise ValueError(error)
            profile = {**clean, "id": supplied_profile.get("id", "agent-machine")}
        else:
            profile = get_machine(snap["active_machine_id"])
        if not profile:
            raise ValueError("Perfil de máquina no encontrado")
        repository = RuntimeSettings.load().repository()
        materialized = repository.materialize(str(path or ""))
        temporary = materialized if materialized.name.startswith("zeuz-send-") else None
        # start_transfer replaces the visible status only once it owns the port,
        # so a rejected second send keeps the running transfer's progress.
        ok, error = serial_transfer.start_transfer(
            snap["active_device"], profile, str(materialized), Path(path).name
        )
        if not ok:
            self._discard_temporary(temporary)
            raise Conflict(error or "No se pudo iniciar el envío")
        threading.Thread(target=self._cleanup_after_transfer, args=(temporary,), daemon=True).start()
        return state.snapshot()["transfer"].get("transfer_id")

    def _cleanup_after_transfer(self, temporary: Path | None) -> None:
        import time

        while state.snapshot()["transfer"]["status"] in {"idle", "sending"}:
            time.sleep(0.5)
        self._discard_temporary(temporary)

    @staticmethod
    def _discard_temporary(temporary: Path | None) -> None:
        # Each request removes only its own copy: a rejected send must not
        # delete or replace the file that the running transfer still reads.
        if temporary:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class Conflict(Exception):
    pass


class Handler(BaseHTTPRequestHandler):
    server_version = f"ZeuzDNC/{installed_version()}"
    # A client that sleeps or leaves the Wi-Fi mid-request leaves a half-open
    # connection; without a limit it held one server thread forever.
    timeout = 60

    @property
    def controller(self) -> HeadlessController:
        return self.server.controller  # type: ignore[attr-defined]

    def log_message(self, format: str, *args) -> None:
        print(f"{self.client_address[0]} {format % args}")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/api/system/"):
            self._system("GET")
            return
        if path.startswith("/api/update/"):
            self._update("GET")
            return
        if path.startswith("/v1/"):
            self._mobile("GET")
            return
        if path.startswith("/api/workshop/"):
            self._workshop("GET")
            return
        if path in {"/", "/api/info", "/api/health"}:
            self._json(self.controller.info())
        elif path == "/api/state":
            self._json({**state.snapshot(), **self.controller.info()})
        elif path == "/api/machines":
            self._json(load_machines())
        elif path == "/api/transfer/status":
            self._json(state.snapshot()["transfer"])
        else:
            self._json({"ok": False, "error": "Ruta no encontrada"}, HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlsplit(self.path).path
        if path.startswith("/api/system/"):
            self._system("POST")
            return
        if path.startswith("/api/update/"):
            self._update("POST")
            return
        if path in {"/api/agent/pair", "/api/workshop/configure"} and update_auth.paired_token() and not update_auth.authorized(self.headers.get("Authorization", "")):
            self._json({"ok": False, "error": "Se requiere el Agent vinculado para cambiar esta configuración"}, 403)
            return
        if path.startswith("/v1/"):
            self._mobile("POST")
            return
        try:
            body = self._body()
            if path.startswith("/api/workshop/"):
                self._json(workshop.dispatch("POST", self.path, body))
                return
            if path == "/api/device/select":
                if not state.select_device(body.get("path")):
                    raise Conflict("Puerto RS232 no disponible")
                result = {"ok": True}
            elif path == "/api/machine/select":
                machine_id = body.get("id")
                if not machine_id or not get_machine(machine_id):
                    raise ValueError("Máquina inválida")
                state.select_machine(machine_id)
                result = {"ok": True}
            elif path == "/api/machine/save":
                machine, error = save_machine(body)
                if error:
                    raise ValueError(error)
                result = {"ok": True, "machine": machine}
            elif path == "/api/machine/delete":
                ok, error = delete_machine(body.get("id"))
                if not ok:
                    raise ValueError(error or "Máquina no encontrada")
                result = {"ok": True}
            elif path == "/api/send":
                transfer_id = self.controller.send(body.get("path", ""), body.get("machine"))
                result = {"ok": True, **({"transfer_id": transfer_id} if transfer_id else {})}
            elif path == "/api/send/cancel":
                serial_transfer.request_cancel()
                result = {"ok": True}
            elif path == "/api/agent/pair":
                result = self.controller.pair_agent(body.get("url", ""), body.get("code", ""), body.get("management_only") is True)
            else:
                self._json({"ok": False, "error": "Ruta no encontrada"}, HTTPStatus.NOT_FOUND)
                return
            self._json(result)
        except Conflict as exc:
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.CONFLICT)
        except (ValueError, OSError) as exc:
            self._json({"ok": False, "error": str(exc)}, getattr(exc, "status", HTTPStatus.BAD_REQUEST))
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_GATEWAY)

    def _system(self, method):
        if not update_auth.authorized(self.headers.get("Authorization", "")):
            self._json({"ok": False, "error": "Se requiere el Agent vinculado para administrar el sistema"}, 401)
            return
        try:
            if method == "POST" and int(self.headers.get("Content-Length", "0")) > 2048:
                raise ValueError("Solicitud de sistema demasiado grande")
            result = system_management.dispatch(method, urlsplit(self.path).path,
                                                self._body() if method == "POST" else None)
            self._json(result)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, getattr(exc, "status", 400))

    def _update(self, method):
        if not update_auth.authorized(self.headers.get("Authorization", "")):
            self._json({"ok": False, "error": "Vincula este equipo con tu Agent para administrar actualizaciones"}, 401)
            return
        try:
            self._json(remote_updates.dispatch(self.server.updates, method, urlsplit(self.path).path, self._body() if method == "POST" else None))
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, getattr(exc, "status", 400))

    def _mobile(self, method: str):
        from zeuz_core.mobile_api import dispatch
        try:
            result = dispatch(self, method)
            if result is not None:
                self._json(result)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, getattr(exc, "status", 400))

    def _workshop(self, method: str) -> None:
        try:
            self._json(workshop.dispatch(method, self.path, self._body() if method == "PUT" else None))
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, getattr(exc, "status", 400))

    def do_PUT(self) -> None:
        self._mobile("PUT") if self.path.startswith("/v1/") else self._workshop("PUT")

    def do_DELETE(self) -> None:
        self._mobile("DELETE") if self.path.startswith("/v1/") else self._workshop("DELETE")

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Content-Length inválido")
        if length < 0 or length > 180 * 1024 * 1024:
            raise ValueError("Solicitud demasiado grande")
        try:
            value = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError as exc:
            raise ValueError("JSON inválido") from exc
        if not isinstance(value, dict):
            raise ValueError("El cuerpo debe ser un objeto JSON")
        return value

    def _json(self, value, status: int = HTTPStatus.OK) -> None:
        payload = json.dumps(value, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(payload)


class Server(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, address, controller: HeadlessController):
        self.controller = controller
        self.updates = remote_updates.UpdateManager()
        super().__init__(address, Handler)


def main() -> None:
    from zeuz_core.transfer_diagnostics import configure_transfer_diagnostics
    configure_transfer_diagnostics()
    usb_monitor.start_usb_monitor()
    server = Server(("0.0.0.0", 5000), HeadlessController())
    server.updates.start()
    try:
        server.serve_forever()
    finally:
        server.updates.stop()
        server.server_close()


if __name__ == "__main__":
    main()
