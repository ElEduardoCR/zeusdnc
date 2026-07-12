"""Carga y edicion de perfiles de maquina en config/machines.json.

El archivo se relee del disco en cada consulta (asi los cambios se ven sin
reiniciar) y se escribe de forma atomica y con un lock para que la edicion
desde la interfaz no corrompa el JSON si coinciden dos operaciones.
"""
import json
import os
import re
import threading

MACHINES_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "config", "machines.json")

_lock = threading.Lock()

VALID_PARITY = {"N", "E", "O", "M", "S"}
VALID_FLOW = {"xonxoff", "rtscts"}
VALID_TERM = {"CR", "CRLF", "LF"}


def load_machines():
    try:
        with open(MACHINES_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return []
    return data.get("machines", [])


def get_machine(machine_id):
    for m in load_machines():
        if m.get("id") == machine_id:
            return m
    return None


def _save_all(machines):
    os.makedirs(os.path.dirname(MACHINES_PATH), exist_ok=True)
    tmp = MACHINES_PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"machines": machines}, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MACHINES_PATH)


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
    }, None


def _slugify(name):
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    return slug or "maquina"


def save_machine(data):
    """Crea (si no trae id) o actualiza un perfil. Devuelve (perfil, None)
    o (None, error)."""
    clean, err = validate_machine(data)
    if err:
        return None, err

    with _lock:
        machines = load_machines()
        machine_id = data.get("id")

        if machine_id:
            for m in machines:
                if m.get("id") == machine_id:
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
        machines.append(clean)
        _save_all(machines)
        return clean, None


def delete_machine(machine_id):
    with _lock:
        machines = load_machines()
        remaining = [m for m in machines if m.get("id") != machine_id]
        if len(remaining) == len(machines):
            return False, "Maquina no encontrada"
        _save_all(remaining)
    return True, None
