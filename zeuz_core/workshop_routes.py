"""Route mobile operations directly from the workshop server to each CNC Pi."""
import json
import urllib.request
import urllib.error

from machines import load_machines
from zeuz_core.workshop import settings


def request(route, method, path, body=None, authorization=""):
    raw = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f'http://{route["host"]}:{route["port"]}{path}', data=raw, method=method, headers={"Content-Type": "application/json", **({"Authorization": authorization} if authorization else {})})
    try:
        with urllib.request.urlopen(req, timeout=5) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        try:
            detail = json.load(exc).get("error", str(exc))
        except Exception:
            detail = str(exc)
        error = ValueError(detail)
        error.status = exc.code
        raise error from exc


def routes():
    return settings().get("machine_routes", [])


def catalog_id(route, device_id):
    match = next((m for m in route.get("machines", []) if m["id"] == device_id), None)
    if match:
        return match.get("catalog_id", device_id)
    if route.get("local"):
        return device_id
    # Stable namespace for profiles created after the computer left.
    import hashlib
    suffix = hashlib.sha256(f'{route["host"]}:{route["port"]}'.encode()).hexdigest()[:8]
    return device_id + "-" + suffix


def machines():
    local_route = next((r for r in routes() if r.get("local")), {"local": True})
    values = {catalog_id(local_route, m["id"]): {**m, "id": catalog_id(local_route, m["id"]), "dnc_host": local_route.get("host"), "dnc_port": local_route.get("port")} for m in load_machines()}
    for route in routes():
        if route.get("local"):
            continue
        try:
            remote = request(route, "GET", "/api/machines")
        except OSError:
            remote = [dict(m, offline=True) for m in route.get("machines", [])]
        for machine in remote:
            key = catalog_id(route, machine["id"])
            if key in values:
                raise ValueError("Hay IDs de máquina repetidos. Resuelve el conflicto en Agent.")
            values[key] = {**machine, "id": key, "dnc_host": route.get("host"), "dnc_port": route.get("port")}
    return list(values.values())


def route_for(machine_id):
    local_route = next((r for r in routes() if r.get("local")), {"local": True})
    for machine in load_machines():
        if catalog_id(local_route, machine["id"]) == machine_id:
            return {**local_route, "device_id": machine["id"]}
    for route in routes():
        if route.get("local"):
            continue
        for machine in route.get("machines", []):
            if catalog_id(route, machine["id"]) == machine_id:
                return {**route, "device_id": machine["id"]}
        try:
            for machine in request(route, "GET", "/api/machines"):
                if catalog_id(route, machine["id"]) == machine_id:
                    return {**route, "device_id": machine["id"]}
        except OSError:
            continue
    raise ValueError("Máquina no encontrada en el taller")
