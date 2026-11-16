#!/usr/bin/python3
"""Root-owned, fixed-purpose clock repair; never imports replaceable app code."""
from __future__ import annotations

import fcntl
import json
import math
import os
from pathlib import Path
import pwd
import stat
import tempfile
import time
import uuid

ROOT = Path("/var/lib/zeuz-clock")
REQUEST = ROOT / "inbox/request.json"
RESULTS = ROOT / "results.json"
OPERATION_LOCK = Path("/var/lib/zeuz/operation.lock")
BOOT_ID = Path("/proc/sys/kernel/random/boot_id")
MIN_UTC = 1577836800  # 2020-01-01
MAX_UTC = 4102444800  # 2100-01-01, exclusive
MAX_FORWARD = 5 * 366 * 86400
MAX_BACKWARD = 300
MAX_AGE = 60


def read_json(path, limit, *, owner=None):
    descriptor = os.open(path, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
    with os.fdopen(descriptor, "rb") as handle:
        details = os.fstat(handle.fileno())
        if not stat.S_ISREG(details.st_mode) or details.st_size > limit:
            raise ValueError("Archivo de reloj inválido")
        if owner is not None and details.st_uid != owner:
            raise ValueError("Propietario de solicitud inválido")
        raw = handle.read(limit + 1)
        if len(raw) > limit:
            raise ValueError("Solicitud de reloj demasiado grande")
    return json.loads(raw)


def atomic_write(path, raw, mode=0o644):
    descriptor, temporary = tempfile.mkstemp(prefix=".clock-", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), mode)
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        descriptor = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def validate(value, *, current, monotonic, boot_id):
    if not isinstance(value, dict) or set(value) != {"request_id", "utc_unix", "monotonic", "boot_id"}:
        raise ValueError("Solicitud de reloj inválida")
    if not isinstance(value["request_id"], str) or str(uuid.UUID(value["request_id"])) != value["request_id"]:
        raise ValueError("Identificador de solicitud inválido")
    stamp, issued = value["utc_unix"], value["monotonic"]
    if type(stamp) is not int or not MIN_UTC <= stamp < MAX_UTC:
        raise ValueError("La hora debe estar entre 2020 y 2100 UTC")
    if type(issued) not in (float, int) or not math.isfinite(issued):
        raise ValueError("Tiempo de solicitud inválido")
    age = monotonic - issued
    if value["boot_id"] != boot_id or not 0 <= age < MAX_AGE:
        raise ValueError("Solicitud de reloj vencida; solicita una nueva sincronización")
    target = stamp + age
    if not MIN_UTC <= target < MAX_UTC or target < current - MAX_BACKWARD or target > current + MAX_FORWARD:
        raise ValueError("El ajuste excede el límite: 5 años hacia adelante o 5 minutos hacia atrás")
    return target


def persist_clock(timestamp, root):
    fake = root / "etc/fake-hwclock.data"
    sync = root / "var/lib/systemd/timesync/clock"
    if fake.is_symlink() or sync.is_symlink():
        raise ValueError("El estado persistente del reloj no puede ser un enlace")
    raw = (time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(timestamp)) + "\n").encode()
    descriptor = os.open(fake, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    with os.fdopen(descriptor, "wb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("Estado fake-hwclock inválido")
        handle.write(raw)
        handle.truncate()
        handle.flush()
        os.fsync(handle.fileno())
    descriptor = os.open(sync, os.O_WRONLY | os.O_CREAT | os.O_NOFOLLOW, 0o644)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError("Estado timesync inválido")
        os.utime(descriptor, (timestamp, timestamp))
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def check_clock_files(root):
    for relative in ("etc/fake-hwclock.data", "var/lib/systemd/timesync/clock"):
        descriptor = os.open(root / relative, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK)
        try:
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                raise ValueError("Estado persistente del reloj inválido")
        finally:
            os.close(descriptor)


def execute(*, request_path=REQUEST, results_path=RESULTS, lock_path=OPERATION_LOCK,
            filesystem_root=Path("/"), current=time.time, monotonic=time.monotonic,
            boot_id=None, owner=None, set_clock=None):
    """All host-changing operations are injectable for isolated tests."""
    if boot_id is None:
        boot_id = BOOT_ID.read_text().strip()
    if owner is None:
        owner = pwd.getpwnam("zeuz").pw_uid
    value = read_json(request_path, 2048, owner=owner)
    try:
        history = read_json(results_path, 32768)
    except FileNotFoundError:
        history = []
    if not isinstance(history, list) or len(history) > 32 or any(not isinstance(item, dict) for item in history):
        raise ValueError("Historial de reloj inválido")
    raw_id = value.get("request_id") if isinstance(value, dict) else None
    try:
        request_id = str(uuid.UUID(raw_id)) if isinstance(raw_id, str) else None
        if request_id != raw_id:
            request_id = None
    except ValueError:
        request_id = None
    previous = next((item for item in history if request_id and item.get("request_id") == request_id), None)
    if previous:
        if previous.get("requested_utc") != value.get("utc_unix"):
            raise ValueError("No reutilices un identificador con otra hora")
        return previous

    raw_stamp = value.get("utc_unix") if isinstance(value, dict) else None
    result = {"request_id": request_id, "requested_utc": raw_stamp if type(raw_stamp) is int and MIN_UTC <= raw_stamp < MAX_UTC else None,
              "phase": "failed", "error": ""}
    try:
        # Validate before opening even the fixed operation lock.
        target = validate(value, current=current(), monotonic=monotonic(), boot_id=boot_id)
        descriptor = os.open(lock_path, os.O_RDWR | os.O_NOFOLLOW | os.O_NONBLOCK)
        with os.fdopen(descriptor, "r+") as lock:
            if not stat.S_ISREG(os.fstat(lock.fileno()).st_mode):
                raise ValueError("Bloqueo de operación inválido")
            try:
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ValueError("Hay un envío o una actualización en curso; vuelve a sincronizar al terminar") from exc
            target = validate(value, current=current(), monotonic=monotonic(), boot_id=boot_id)
            check_clock_files(filesystem_root)
            # No arbitrary command, shell, path, URL, or executable is accepted.
            if set_clock is None:
                time.clock_settime(time.CLOCK_REALTIME, target)
            else:
                set_clock(target)
            persist_clock(target, filesystem_root)
            result.update(phase="succeeded", applied_utc=int(target))
    except (OSError, ValueError) as exc:
        result["error"] = str(exc)[:300]
    history.append(result)
    atomic_write(results_path, (json.dumps(history[-32:]) + "\n").encode())
    return result


if __name__ == "__main__":
    # Only the fixed unit invokes this file; arguments cannot redirect paths.
    import sys
    if len(sys.argv) != 1:
        raise SystemExit("El servicio de reloj no acepta argumentos")
    result = execute()
    print(json.dumps(result))
    raise SystemExit(0 if result["phase"] == "succeeded" else 1)
