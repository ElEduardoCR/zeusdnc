from __future__ import annotations

import os
import subprocess
import time
from collections.abc import Callable, Sequence


Runner = Callable[..., subprocess.CompletedProcess[str]]


def _split_nmcli(line: str) -> list[str]:
    """Divide la salida `--terse --escape yes` sin romper SSID con dos puntos."""

    fields: list[str] = []
    current: list[str] = []
    escaped = False
    for character in line:
        if escaped:
            current.append(character)
            escaped = False
        elif character == "\\":
            escaped = True
        elif character == ":":
            fields.append("".join(current))
            current = []
        else:
            current.append(character)
    if escaped:
        current.append("\\")
    fields.append("".join(current))
    return fields


class WifiManager:
    """Acceso mínimo a NetworkManager para la interfaz táctil."""

    def __init__(
        self,
        runner: Runner = subprocess.run,
        command_prefix: Sequence[str] | None = None,
        interface: str = "wlan0",
    ) -> None:
        self._runner = runner
        self._prefix = list(command_prefix) if command_prefix is not None else (
            [] if os.geteuid() == 0 else ["sudo", "-n"]
        )
        self.interface = interface

    def _run(self, arguments: Sequence[str], timeout: int = 20) -> str:
        result = self._runner(
            [*self._prefix, "nmcli", *arguments],
            text=True,
            capture_output=True,
            timeout=timeout,
            check=False,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "NetworkManager no respondió").strip()
            raise RuntimeError(detail[:300])
        return result.stdout

    def status(self) -> dict:
        output = self._run(
            [
                "--terse",
                "--escape",
                "yes",
                "--fields",
                "DEVICE,TYPE,STATE,CONNECTION",
                "device",
                "status",
            ]
        )
        device = self.interface
        ssid = ""
        connected = False
        for line in output.splitlines():
            fields = _split_nmcli(line)
            if len(fields) < 4 or fields[1] != "wifi":
                continue
            if fields[0] == self.interface or not connected:
                device = fields[0]
                connected = fields[2] in {"connected", "conectado"}
                ssid = fields[3] if connected else ""
            if fields[0] == self.interface:
                break

        ip = ""
        if connected:
            addresses = self._run(
                ["--get-values", "IP4.ADDRESS", "device", "show", device]
            )
            for address in addresses.splitlines():
                clean = address.strip().split("/", 1)[0]
                if clean and not clean.startswith("127."):
                    ip = clean
                    break
        return {
            "connected": connected,
            "ssid": ssid,
            "ip": ip,
            "interface": device,
        }

    def scan(self) -> list[dict]:
        self._run(["radio", "wifi", "on"])
        output = self._run(
            [
                "--terse",
                "--escape",
                "yes",
                "--fields",
                "IN-USE,SSID,SIGNAL,SECURITY",
                "device",
                "wifi",
                "list",
                "--rescan",
                "yes",
                "ifname",
                self.interface,
            ],
            timeout=35,
        )
        by_ssid: dict[str, dict] = {}
        for line in output.splitlines():
            fields = _split_nmcli(line)
            if len(fields) < 4:
                continue
            active, ssid, signal, security = fields[:4]
            ssid = ssid.strip()
            if not ssid:
                continue
            try:
                strength = max(0, min(100, int(signal)))
            except ValueError:
                strength = 0
            item = {
                "ssid": ssid,
                "signal": strength,
                "security": security.strip() or "Abierta",
                "active": active.strip() in {"*", "yes", "sí"},
            }
            previous = by_ssid.get(ssid)
            if previous is None or item["signal"] > previous["signal"]:
                by_ssid[ssid] = item
        return sorted(
            by_ssid.values(),
            key=lambda item: (not item["active"], -item["signal"], item["ssid"].lower()),
        )

    def connect(self, ssid: str, password: str) -> dict:
        clean_ssid = str(ssid).strip()
        if not clean_ssid or len(clean_ssid.encode("utf-8")) > 32:
            raise ValueError("El nombre de la red Wi-Fi no es válido")
        if len(str(password).encode("utf-8")) > 63:
            raise ValueError("La contraseña Wi-Fi no es válida")

        self._run(["radio", "wifi", "on"])
        command = [
            "--wait",
            "45",
            "device",
            "wifi",
            "connect",
            clean_ssid,
            "ifname",
            self.interface,
        ]
        if password:
            command.extend(["password", str(password)])
        self._run(command, timeout=55)

        snapshot = self.status()
        for _ in range(10):
            if snapshot["connected"] and snapshot["ip"]:
                return snapshot
            time.sleep(1)
            snapshot = self.status()
        if not snapshot["connected"]:
            raise RuntimeError("Zeuz no pudo conectarse a la red Wi-Fi")
        return snapshot
