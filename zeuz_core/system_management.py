"""Authenticated fixed-purpose clock repair and bounded transfer diagnostics."""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import stat
import subprocess
import tempfile
import threading
import time
import uuid

from .operation_guard import OperationLease, Busy

ROOT = Path("/var/lib/zeuz-clock")
REQUEST_PATH = ROOT / "inbox/request.json"
RESULTS_PATH = ROOT / "results.json"
RUNNER_PATH = Path("/usr/local/lib/zeuz/clock_runner.py")
BOOT_ID_PATH = Path("/proc/sys/kernel/random/boot_id")
LOG_PATH = Path("/var/lib/zeuz/transfer-errors.log")
_lock = threading.Lock()
MIN_UTC, MAX_UTC = 1577836800, 4102444800
MAX_FORWARD, MAX_BACKWARD, MAX_AGE = 5 * 366 * 86400, 300, 60


def _read_json(path, limit):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        details = os.fstat(handle.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_size > limit:
            raise ValueError("Archivo de reloj inválido")
        raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Archivo de reloj demasiado grande")
        return json.loads(raw)


def _results():
    try:
        value = _read_json(RESULTS_PATH, 32768)
    except FileNotFoundError:
        return []
    if not isinstance(value, list) or len(value) > 32 or any(not isinstance(item, dict) for item in value):
        raise ValueError("Historial de reloj inválido")
    return value


def _fresh_request():
    try:
        value = _read_json(REQUEST_PATH, 2048)
        age = time.monotonic() - value["monotonic"]
        if value["boot_id"] == BOOT_ID_PATH.read_text().strip() and 0 <= age < MAX_AGE:
            return value
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        pass
    return None


def clock_status():
    history = _results()
    result = history[-1] if history else {}
    request = _fresh_request()
    if request and not any(item.get("request_id") == request["request_id"] for item in history):
        result = {"phase": "pending", "request_id": request["request_id"], "error": ""}
    elif request is None:
        try:
            expired = _read_json(REQUEST_PATH, 2048)
            if not any(item.get("request_id") == expired.get("request_id") for item in history):
                result = {"phase": "failed", "request_id": expired.get("request_id"),
                          "error": "El servicio de reloj no confirmó la solicitud; vuelve a sincronizar"}
        except (FileNotFoundError, ValueError, AttributeError):
            pass
    # Read after the persisted result: the helper may have corrected the clock
    # while this request was reading it, and success must not carry the old UTC.
    now = time.time()
    return {"supported": RUNNER_PATH.is_file(), "utc_unix": int(now),
            "utc": datetime.fromtimestamp(now, timezone.utc).isoformat(),
            "phase": result.get("phase", "idle"), "request_id": result.get("request_id"),
            "error": result.get("error", "")}


def sync_clock(body):
    if set(body) != {"utc_unix", "request_id"}:
        raise ValueError("Usa únicamente utc_unix y request_id")
    request_id, stamp = body["request_id"], body["utc_unix"]
    if not isinstance(request_id, str) or str(uuid.UUID(request_id)) != request_id:
        raise ValueError("Identificador de solicitud inválido")
    if type(stamp) is not int or not MIN_UTC <= stamp < MAX_UTC:
        raise ValueError("La hora debe estar entre 2020 y 2100 UTC")
    with _lock:
        history = _results()
        previous = next((item for item in history if item.get("request_id") == request_id), None)
        pending = _fresh_request()
        previous = previous or (pending if pending and pending["request_id"] == request_id else None)
        if previous:
            if previous.get("requested_utc", previous.get("utc_unix")) != stamp:
                raise ValueError("No reutilices un identificador con otra hora")
            status = clock_status()
            return {**status, "request_id": request_id,
                    "phase": previous.get("phase", "pending"), "error": previous.get("error", "")}
        if pending and not any(item.get("request_id") == pending["request_id"] for item in history):
            raise Busy("Ya hay una sincronización de reloj pendiente")
        now = time.time()
        if stamp < now - MAX_BACKWARD or stamp > now + MAX_FORWARD:
            raise ValueError("El ajuste excede el límite: 5 años hacia adelante o 5 minutos hacia atrás")
        if not RUNNER_PATH.is_file():
            raise ValueError("Falta instalar el servicio de sincronización de reloj")
        # Avoid queuing repairs during a transfer; the root helper also locks.
        with OperationLease(update=True):
            request = {**body, "boot_id": BOOT_ID_PATH.read_text().strip(), "monotonic": time.monotonic()}
            descriptor, temporary = tempfile.mkstemp(prefix=".request-", dir=REQUEST_PATH.parent)
            try:
                with os.fdopen(descriptor, "w") as handle:
                    json.dump(request, handle)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temporary, REQUEST_PATH)
            finally:
                if os.path.exists(temporary):
                    os.unlink(temporary)
        try:
            subprocess.run(["/usr/bin/systemctl", "--no-block", "start", "zeuz-clock-sync.service"],
                           check=True, capture_output=True, timeout=5)
        except (OSError, subprocess.SubprocessError) as exc:
            REQUEST_PATH.unlink(missing_ok=True)
            raise ValueError("No se pudo iniciar el servicio de reloj") from exc
        return clock_status()


def diagnostics():
    """Only the existing serial log; never configuration, journal, or secrets."""
    from state import state
    from serial_transfer import get_serial_diagnostics
    blocks, remaining = [], 32768
    for path in (LOG_PATH, LOG_PATH.with_name(LOG_PATH.name + ".1")):
        if remaining <= 0:
            break
        try:
            descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
            with os.fdopen(descriptor, "rb") as handle:
                details = os.fstat(handle.fileno())
                if not stat.S_ISREG(details.st_mode):
                    continue
                count = min(details.st_size, remaining)
                handle.seek(-count, os.SEEK_END)
                block = handle.read(count)
                if details.st_size > count:
                    block = block.partition(b"\n")[2]
                blocks.insert(0, block)
                remaining -= count
        except FileNotFoundError:
            continue
    lines = b"\n".join(blocks).decode("utf-8", errors="replace").splitlines()[-200:]
    return {"ok": True, "clock": clock_status(), "transfer": state.snapshot()["transfer"],
            "serial": get_serial_diagnostics(),
            "log_lines": lines, "max_log_bytes": 32768, "max_log_lines": 200}


def dispatch(method, path, body=None):
    if method == "GET" and path == "/api/system/clock/status":
        return clock_status()
    if method == "POST" and path == "/api/system/clock/sync":
        return sync_clock(body or {})
    if method == "GET" and path == "/api/system/diagnostics":
        return diagnostics()
    raise ValueError("Ruta de administración no encontrada")
