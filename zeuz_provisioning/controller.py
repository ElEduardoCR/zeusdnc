from __future__ import annotations

import json
import ipaddress
import os
import socket
import subprocess
import threading
from pathlib import Path
from typing import Callable


STATE_PATH = Path("/var/lib/zeuz/network.json")


def _hostname() -> str:
    return socket.gethostname().strip() or "zeuz-dnc"


def _local_ip() -> str:
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(("192.0.2.1", 9))
            return str(sock.getsockname()[0])
    except OSError:
        return ""


def _wifi_ip(runner: Callable[..., subprocess.CompletedProcess[str]]) -> str:
    """Devuelve la IPv4 de wlan0 incluso si Ethernet sigue conectado."""
    try:
        result = runner(
            ["nmcli", "-g", "IP4.ADDRESS", "device", "show", "wlan0"],
            text=True,
            capture_output=True,
            timeout=15,
            check=False,
        )
        if result.returncode == 0:
            for line in result.stdout.splitlines():
                candidate = line.strip().split("/", 1)[0]
                try:
                    return str(ipaddress.ip_address(candidate))
                except ValueError:
                    continue
    except (OSError, subprocess.SubprocessError):
        pass
    return _local_ip()


def _save_machine(machine: dict) -> tuple[dict | None, str | None]:
    # Import tardío para que el controlador siga siendo comprobable fuera de
    # la imagen completa y para reutilizar exactamente la validación de la API.
    from machines import load_machines, save_machine

    name = str(machine.get("name", "")).strip().casefold()
    existing = next(
        (
            value for value in load_machines()
            if str(value.get("name", "")).strip().casefold() == name
        ),
        None,
    )
    if existing and existing.get("id"):
        machine = {**machine, "id": existing["id"]}
    return save_machine(machine)


class ProvisioningController:
    """Valida el comando BLE y conecta NetworkManager sin registrar secretos."""

    def __init__(
        self,
        state_path: Path = STATE_PATH,
        runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        machine_saver: Callable[[dict], tuple[dict | None, str | None]] = _save_machine,
    ) -> None:
        self.state_path = state_path
        self._runner = runner
        self._machine_saver = machine_saver
        self._lock = threading.Lock()
        self._listeners: list[Callable[[dict], None]] = []
        self._status = {
            "device_name": _hostname(),
            "state": "ready",
            "ssid": "",
            "ip": "",
            "api_port": 5000,
            "machine_id": "",
            "error": "",
        }

    def add_listener(self, listener: Callable[[dict], None]) -> None:
        self._listeners.append(listener)

    def snapshot(self) -> dict:
        with self._lock:
            return dict(self._status)

    def encoded_snapshot(self) -> bytes:
        return json.dumps(self.snapshot(), ensure_ascii=False, separators=(",", ":")).encode()

    def handle_command(self, payload: bytes) -> tuple[bool, str]:
        try:
            command = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            return False, "Solicitud de configuración inválida"
        if not isinstance(command, dict):
            return False, "Solicitud de configuración inválida"

        action = command.get("action")
        if action in {"machine", "configure_machine"}:
            return self._configure_machine(command)
        if action not in {"wifi", "configure_wifi"}:
            return False, "Acción de configuración desconocida"

        ssid = str(command.get("s", command.get("ssid", ""))).strip()
        password = str(command.get("p", command.get("password", "")))
        if not ssid or len(ssid.encode("utf-8")) > 32:
            return False, "El nombre de la red Wi-Fi no es válido"
        password_size = len(password.encode("utf-8"))
        if password and not 8 <= password_size <= 63:
            return False, "La contraseña Wi-Fi no es válida"

        with self._lock:
            if self._status["state"] == "connecting":
                return False, "Zeuz ya está intentando conectarse"
            self._status.update(state="connecting", ssid=ssid, ip="", error="")
        self._notify()
        threading.Thread(
            target=self._connect,
            args=(ssid, password),
            name="zeuz-wifi-provision",
            daemon=True,
        ).start()
        return True, "Conectando"

    def _configure_machine(self, command: dict) -> tuple[bool, str]:
        value = command.get("m", command.get("machine", {}))
        if not isinstance(value, dict):
            return False, "La configuración de la máquina no es válida"
        machine = {
            "name": value.get("n", value.get("name", "")),
            "baudrate": value.get("b", value.get("baudrate")),
            "bytesize": value.get("d", value.get("bytesize")),
            "parity": value.get("p", value.get("parity", "")),
            "stopbits": value.get("s", value.get("stopbits")),
            "flow_control": value.get("f", value.get("flow_control", "")),
            "line_terminator": value.get("l", value.get("line_terminator", "")),
            "dtr": value.get("t", value.get("dtr", False)),
            "rts": value.get("r", value.get("rts", False)),
            "dripfeed": value.get("g", value.get("dripfeed", False)),
        }
        try:
            saved, error = self._machine_saver(machine)
        except (OSError, ValueError) as exc:
            return False, str(exc)
        if error or not saved:
            return False, error or "No se pudo guardar la máquina"
        with self._lock:
            self._status.update(machine_id=str(saved.get("id", "")), error="")
        self._notify()
        return True, "Máquina guardada"

    def _connect(self, ssid: str, password: str) -> None:
        common_options = {
            "text": True,
            "capture_output": True,
            "timeout": 55,
            "check": False,
        }
        try:
            radio = self._runner(["nmcli", "radio", "wifi", "on"], **common_options)
        except (OSError, subprocess.SubprocessError):
            self._failed("No se pudo activar el radio Wi-Fi")
            return
        if radio.returncode != 0:
            detail = (radio.stderr or radio.stdout or "No se pudo activar el Wi-Fi").strip()
            self._failed(detail[:240])
            return

        command = ["nmcli", "--wait", "45", "device", "wifi", "connect", ssid]
        if password:
            command.extend(["password", password])
        try:
            result = self._runner(command, **common_options)
        except (OSError, subprocess.SubprocessError):
            self._failed("No se pudo iniciar NetworkManager")
            return
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "No se pudo conectar a la red").strip()
            # nmcli puede repetir el SSID, pero nunca debe filtrarse la contraseña.
            self._failed(detail[:240])
            return

        ip = _wifi_ip(self._runner)
        with self._lock:
            self._status.update(state="connected", ssid=ssid, ip=ip, error="")
        try:
            self.state_path.parent.mkdir(parents=True, exist_ok=True)
            self.state_path.write_text(
                json.dumps(
                    {
                        "ssid": ssid,
                        "hostname": _hostname(),
                        "machine_id": self.snapshot()["machine_id"],
                    },
                    ensure_ascii=False,
                ) + "\n",
                encoding="utf-8",
            )
            os.chmod(self.state_path, 0o600)
        except OSError:
            # La conexión ya está lista; no convertir un fallo del marcador en
            # un falso negativo para el iPhone.
            pass
        self._notify()

    def _failed(self, message: str) -> None:
        with self._lock:
            self._status.update(state="error", ip="", error=message)
        self._notify()

    def _notify(self) -> None:
        snapshot = self.snapshot()
        for listener in tuple(self._listeners):
            try:
                listener(snapshot)
            except Exception:
                continue
