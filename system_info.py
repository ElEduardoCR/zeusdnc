"""Info de sistema para la barra superior: IP local y configuracion de WiFi.

El WiFi se maneja con nmcli (NetworkManager, el de Raspberry Pi OS
Bookworm). Si nmcli no esta disponible (p.ej. en desarrollo en otra PC),
las funciones degradan sin romper la app.
"""
import re
import socket
import subprocess
import time

_ip_cache = {"ip": None, "t": 0.0}
_wifi_cache = {"ssid": None, "t": 0.0}


def get_ip():
    """IP local de salida (sin enviar trafico). None si no hay red."""
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return None
    finally:
        s.close()


def get_ip_cached(ttl=5):
    now = time.time()
    if now - _ip_cache["t"] > ttl:
        _ip_cache["ip"] = get_ip()
        _ip_cache["t"] = now
    return _ip_cache["ip"]


def _nmcli(args, timeout=20):
    return subprocess.run(
        ["nmcli"] + args, capture_output=True, text=True, timeout=timeout
    )


def _split_terse(line):
    # nmcli -t separa con ':' y escapa los ':' internos como '\:'
    parts = re.split(r"(?<!\\):", line)
    return [p.replace("\\:", ":").replace("\\\\", "\\") for p in parts]


def _wifi_ssid():
    try:
        r = _nmcli(["-t", "-f", "ACTIVE,SSID", "device", "wifi"], timeout=8)
        for line in r.stdout.splitlines():
            if line.startswith("yes:"):
                return line.split(":", 1)[1]
    except Exception:  # noqa: BLE001
        pass
    return None


def wifi_ssid_cached(ttl=6):
    """SSID de la red WiFi activa (o None). Cacheado para no invocar nmcli en
    cada consulta de estado (que ocurre cada segundo)."""
    now = time.time()
    if now - _wifi_cache["t"] > ttl:
        _wifi_cache["ssid"] = _wifi_ssid()
        _wifi_cache["t"] = now
    return _wifi_cache["ssid"]


def wifi_status():
    return {"ssid": _wifi_ssid(), "ip": get_ip_cached()}


def wifi_scan():
    nets = []
    try:
        _nmcli(["device", "wifi", "rescan"], timeout=25)
    except Exception:  # noqa: BLE001
        pass
    try:
        r = _nmcli(["-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list"], timeout=25)
    except FileNotFoundError:
        return []
    except Exception:  # noqa: BLE001
        return []

    seen = set()
    for line in r.stdout.splitlines():
        parts = _split_terse(line)
        if len(parts) < 3:
            continue
        ssid, signal, security = parts[0], parts[1], parts[2]
        if not ssid or ssid in seen:
            continue
        seen.add(ssid)
        nets.append({
            "ssid": ssid,
            "signal": int(signal) if signal.isdigit() else 0,
            "secure": security not in ("", "--"),
        })
    nets.sort(key=lambda n: n["signal"], reverse=True)
    return nets


def wifi_connect(ssid, password):
    args = ["device", "wifi", "connect", ssid]
    if password:
        args += ["password", password]
    try:
        r = _nmcli(args, timeout=45)
    except subprocess.TimeoutExpired:
        return False, "Tiempo de espera agotado al conectar"
    except FileNotFoundError:
        return False, "nmcli no esta disponible en el sistema"
    except Exception as e:  # noqa: BLE001
        return False, str(e)
    if r.returncode == 0:
        return True, None
    return False, (r.stderr.strip() or r.stdout.strip() or "No se pudo conectar")
