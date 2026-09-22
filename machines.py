"""Carga y edicion de perfiles de maquina en config/machines.json.

El archivo se relee del disco en cada consulta (asi los cambios se ven sin
reiniciar) y se escribe de forma atomica y con un lock para que la edicion
desde la interfaz no corrompa el JSON si coinciden dos operaciones.
"""
import json
import hashlib
import os
import re
import threading
import contextlib
import fcntl

MACHINES_PATH = os.environ.get(
    "ZEUZ_MACHINES_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "machines.json"),
)

_thread_lock = threading.RLock()


@contextlib.contextmanager
def _locked():
    # The touchscreen and headless API are separate processes on the Pi.
    with _thread_lock:
        os.makedirs(os.path.dirname(MACHINES_PATH), exist_ok=True)
        with open(MACHINES_PATH + ".lock", "a") as handle:
            fcntl.flock(handle, fcntl.LOCK_EX)
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)

VALID_PARITY = {"N", "E", "O", "M", "S"}
# "none" = sin control de flujo. serial_transfer ya lo resuelve bien (deja
# xonxoff y rtscts en False); faltaba solo aceptarlo aqui, y sin el la app de
# iPhone no podia guardar un perfil sin control de flujo.
VALID_FLOW = {"xonxoff", "rtscts", "none"}
VALID_TERM = {"CR", "CRLF", "LF"}


def load_machines():
    try:
        with open(MACHINES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except FileNotFoundError:
        return []
    return data.get("machines", [])


def get_machine(machine_id):
    for m in load_machines():
        if m.get("id") == machine_id:
            return m
    return None


def _save_all(machines):
    os.makedirs(os.path.dirname(MACHINES_PATH), exist_ok=True)
    try:
        current = os.stat(MACHINES_PATH)
    except OSError:
        current = None
    tmp = MACHINES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"machines": machines}, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MACHINES_PATH)
    if current is not None:
        os.chmod(MACHINES_PATH, current.st_mode & 0o777)
        try:
            os.chown(MACHINES_PATH, current.st_uid, current.st_gid)
        except PermissionError:
            pass


def validate_machine(data):
    """Devuelve (perfil_limpio, None) o (None, mensaje_de_error)."""
    name = str(data.get("name", "")).strip()
    if not name:
        return None, "El nombre es obligatorio"

    try:
        baudrate = int(data.get("baudrate"))
    except (TypeError, ValueError):
        return None, "Baudrate invalido"
    if baudrate <= 0:
        return None, "Baudrate invalido"

    try:
        bytesize = int(data.get("bytesize"))
    except (TypeError, ValueError):
        return None, "Bits de datos invalido"
    if bytesize not in (5, 6, 7, 8):
        return None, "Bits de datos debe ser 5, 6, 7 u 8"

    parity = str(data.get("parity", "")).upper()
    if parity not in VALID_PARITY:
        return None, "Paridad invalida"

    try:
        stopbits = int(data.get("stopbits"))
    except (TypeError, ValueError):
        return None, "Bits de stop invalido"
    if stopbits not in (1, 2):
        return None, "Bits de stop debe ser 1 o 2"

    flow = str(data.get("flow_control", "")).lower()
    if flow not in VALID_FLOW:
        return None, "Control de flujo invalido"

    term = str(data.get("line_terminator", "")).upper()
    if term not in VALID_TERM:
        return None, "Terminador de linea invalido"

    return {
        "name": name,
        "baudrate": baudrate,
        "bytesize": bytesize,
        "parity": parity,
        "stopbits": stopbits,
        "flow_control": flow,
        "line_terminator": term,
        "dtr": bool(data.get("dtr", False)),
        "rts": bool(data.get("rts", False)),
        "dripfeed": bool(data.get("dripfeed", False)),
    }, None


def _slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "maquina"


def _revision(profile):
    fields = {key: value for key, value in profile.items() if key not in {"id", "revision"} and not key.startswith("dnc_")}
    return int(hashlib.sha256(json.dumps(fields, sort_keys=True, separators=(",", ":")).encode()).hexdigest()[:13], 16)


def save_machine(data):
    """Crea (si no trae id) o actualiza un perfil. Devuelve (perfil, None)
    o (None, error)."""
    clean, err = validate_machine(data)
    if err:
        return None, err

    with _locked():
        machines = load_machines()
        machine_id = data.get("id")

        if machine_id:
            for m in machines:
                if m.get("id") == machine_id:
                    if "revision" in data and data["revision"] != m.get("revision", 0):
                        return None, "El perfil cambió en otro equipo. Vuelve a abrirlo antes de guardar."
                    clean["revision"] = _revision(clean)
                    m.update(clean)
                    m["id"] = machine_id
                    _save_all(machines)
                    return m, None
            return None, "Maquina no encontrada"

        existing = {m.get("id") for m in machines}
        base = _slugify(clean["name"])
        new_id = base
        i = 2
        while new_id in existing:
            new_id = "{}-{}".format(base, i)
            i += 1
        clean["id"] = new_id
        clean["revision"] = _revision(clean)
        machines.append(clean)
        _save_all(machines)
        return clean, None


def delete_machine(machine_id):
    with _locked():
        machines = load_machines()
        remaining = [m for m in machines if m.get("id") != machine_id]
        if len(remaining) == len(machines):
            return False, "Maquina no encontrada"
        _save_all(remaining)
    return True, None


class MachineConflict(ValueError):
    status = 409


def sync_machine(body):
    """Compare-and-swap for Agent; preserve stable IDs on initial replication."""
    profile = body.get("machine", {})
    machine_id = str(profile.get("id", ""))
    if not machine_id or "expected_revision" not in body:
        raise ValueError("Falta id o revisión esperada")
    with _locked():
        values = load_machines()
        current = next((m for m in values if m.get("id") == machine_id), None)
        actual = current.get("revision", 0) if current else None
        if body["expected_revision"] != actual:
            raise MachineConflict("El perfil cambió en la pantalla táctil; vuelve a sincronizar")
        if body.get("delete"):
            _save_all([m for m in values if m.get("id") != machine_id])
            return None
        clean, error = validate_machine(profile)
        if error:
            raise ValueError(error)
        clean.update(id=machine_id, revision=_revision(clean))
        values = [m for m in values if m.get("id") != machine_id] + [clean]
        _save_all(values)
        return clean
