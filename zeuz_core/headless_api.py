from __future__ import annotations

import json
import os
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

import serial_transfer
import usb_monitor
from machines import delete_machine, get_machine, load_machines, save_machine
from state import state
from zeuz_core.pair_agent import pair, write_runtime
from zeuz_core.settings import DEFAULT_SETTINGS_PATH, RuntimeSettings
from zeuz_core.version import installed_version


class HeadlessController:
    def __init__(self) -> None:
        self._temporary_file: Path | None = None
        self._cleanup_lock = threading.Lock()

    @staticmethod
    def info() -> dict:
        settings = RuntimeSettings.load()
        return {
            "ok": True,
            "service": "zeuz-dnc",
            "hostname": os.uname().nodename,
            "version": installed_version(),
            "api": 1,
            "agent_configured": settings.source_type == "agent" and bool(settings.agent_token),
        }

    @staticmethod
    def pair_agent(url: str, code: str) -> dict:
        clean_url = str(url or "").strip().rstrip("/")
        clean_code = "".join(character for character in str(code or "") if character.isdigit())
        if not clean_url.startswith(("http://", "https://")):
            raise ValueError("La dirección de Zeuz Agent no es válida")
        if len(clean_code) != 6:
            raise ValueError("El código de Zeuz Agent debe tener seis dígitos")
        result = pair(clean_url, clean_code)
        write_runtime(DEFAULT_SETTINGS_PATH, clean_url, result["token"])
        RuntimeSettings.load().repository().list("")
        return {"ok": True, "agent_name": result.get("agent_name", "Zeuz Agent")}

    def send(self, path: str) -> None:
        snap = state.snapshot()
        if not snap["usb_devices"]:
            raise Conflict("Cable RS232 no conectado")
        if not snap["active_device"]:
            raise Conflict("Elige a qué puerto RS232 enviar")
        if not snap["active_machine_id"]:
            raise Conflict("Selecciona una máquina antes de enviar")
        if snap["transfer"]["status"] == "sending":
            raise Conflict("Ya hay una transferencia en curso")

        profile = get_machine(snap["active_machine_id"])
        if not profile:
            raise ValueError("Perfil de máquina no encontrado")
        repository = RuntimeSettings.load().repository()
        materialized = repository.materialize(str(path or ""))
        self._temporary_file = materialized if materialized.name.startswith("zeuz-send-") else None
        state.reset_transfer()
        ok, error = serial_transfer.start_transfer(
            snap["active_device"], profile, str(materialized), Path(path).name
        )
        if not ok:
            self._discard_temporary()
            raise Conflict(error or "No se pudo iniciar el envío")
        threading.Thread(target=self._cleanup_after_transfer, daemon=True).start()

    def _cleanup_after_transfer(self) -> None:
        import time

        while state.snapshot()["transfer"]["status"] in {"idle", "sending"}:
            time.sleep(0.5)
        self._discard_temporary()

    def _discard_temporary(self) -> None:
        with self._cleanup_lock:
            temporary = self._temporary_file
            self._temporary_file = None
        if temporary:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass


class Conflict(Exception):
    pass


class Handler(BaseHTTPRequestHandler):
    server_version = f"ZeuzDNC/{installed_version()}"

    @property
    def controller(self) -> HeadlessController:
        return self.server.controller  # type: ignore[attr-defined]

    def log_message(self, format: str, *args) -> None:
        print(f"{self.client_address[0]} {format % args}")

    def do_GET(self) -> None:
        path = urlsplit(self.path).path
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
        try:
            body = self._body()
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
                self.controller.send(body.get("path", ""))
                result = {"ok": True}
            elif path == "/api/send/cancel":
                serial_transfer.request_cancel()
                result = {"ok": True}
            elif path == "/api/agent/pair":
                result = self.controller.pair_agent(body.get("url", ""), body.get("code", ""))
            else:
                self._json({"ok": False, "error": "Ruta no encontrada"}, HTTPStatus.NOT_FOUND)
                return
            self._json(result)
        except Conflict as exc:
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.CONFLICT)
        except (ValueError, OSError) as exc:
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self._json({"ok": False, "error": str(exc)}, HTTPStatus.BAD_GATEWAY)

    def _body(self) -> dict:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Content-Length inválido")
        if length > 64 * 1024:
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
        super().__init__(address, Handler)


def main() -> None:
    usb_monitor.start_usb_monitor()
    Server(("0.0.0.0", 5000), HeadlessController()).serve_forever()


if __name__ == "__main__":
    main()
