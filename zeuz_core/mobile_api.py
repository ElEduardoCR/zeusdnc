"""The Agent v1 contract on a Pi, so iZeuz can work without the computer."""
import hashlib
import hmac
import json
import secrets
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from machines import delete_machine, get_machine, load_machines, save_machine
from state import state
from zeuz_core import workshop, workshop_routes
from zeuz_core.settings import RuntimeSettings


def credentials():
    with workshop._lock:
        value = workshop.settings()
        if not value.get("mobile_token") or not value.get("pairing_code"):
            value.setdefault("mobile_token", secrets.token_urlsafe(32))
            value["pairing_code"] = f"{secrets.randbelow(1000000):06d}"
            workshop.atomic_write(workshop.settings_path(), json.dumps(value).encode())
        return value


def dispatch(handler, method):
    parsed = urlsplit(handler.path)
    path = parsed.path
    query = parse_qs(parsed.query)
    relative = query.get("path", [""])[0]
    value = credentials()
    body = handler._body() if method in {"POST", "PUT"} else {}
    if path in {"/v1/info", "/v1/health"} and method == "GET":
        return {"ok": True, "name": value.get("name", "Servidor Zeuz"), "service": "zeuzagent", "api_version": 1, "pairing_required": True}
    if path == "/v1/pair" and method == "POST":
        if not hmac.compare_digest(str(body.get("code", "")), value["pairing_code"]):
            handler._json({"ok": False, "error": "Código de emparejamiento inválido"}, 403)
            return None
        return {"ok": True, "token": value["mobile_token"], "agent_name": value.get("name", "Servidor Zeuz"), "api_version": 1}
    if path.startswith("/v1/dnc/update/"):
        # Management trusts the original paired Agent, never replaceable mobile credentials.
        from zeuz_core import update_auth, remote_updates
        authorization = handler.headers.get("Authorization", "")
        if not update_auth.authorized(authorization):
            handler._json({"ok": False, "error": "Vincula este equipo con tu Agent"}, 401)
            return None
        machine_id = body.pop("machine_id", None) or query.get("machine_id", [""])[0]
        route = workshop_routes.route_for(machine_id)
        remote_path = path.replace("/v1/dnc/", "/api/")
        if not route.get("local"):
            try:
                return workshop_routes.request(route, method, remote_path, body if method == "POST" else None, authorization=authorization)
            except ValueError as exc:
                if getattr(exc, "status", None) == 404:
                    return {"supported": False, "phase": "unsupported", "error": "El equipo requiere firmware compatible con actualización remota"}
                raise
        return remote_updates.dispatch(handler.server.updates, method, remote_path, body)
    if not hmac.compare_digest(handler.headers.get("Authorization", ""), "Bearer " + value["mobile_token"]):
        handler._json({"ok": False, "error": "Emparejamiento requerido"}, 401)
        return None
    if path == "/v1/dnc/machines" and method == "GET":
        return workshop_routes.machines()
    if path.startswith("/v1/dnc/") and path not in {"/v1/dnc/device/select"}:
        machine_id = body.get("machine_id") or body.get("id") or query.get("machine_id", [""])[0]
        if machine_id:
            route = workshop_routes.route_for(machine_id)
            if "id" in body:
                body["id"] = route["device_id"]
            if "machine_id" in body:
                body["machine_id"] = route["device_id"]
            if not route.get("local"):
                remote_path = path.replace("/v1/dnc/", "/api/")
                if path == "/v1/dnc/send":
                    # Resolve the latest confirmed serial profile at the destination.
                    remote = workshop_routes.request(route, "GET", "/api/machines")
                    machine = next((m for m in remote if m["id"] == route["device_id"]), None)
                    if not machine:
                        raise ValueError("Máquina no encontrada")
                    body = {**body, "machine": machine}
                result = workshop_routes.request(route, method, remote_path, body if method == "POST" else None)
                if isinstance(result, dict) and result.get("machine"):
                    result["machine"]["id"] = machine_id
                return result
    if path == "/v1/dnc/machine/save" and method == "POST":
        saved, error = save_machine(body)
        if error:
            raise ValueError(error)
        if body.get("id"):
            saved = {**saved, "id": machine_id}
        return {"ok": True, "machine": saved}
    if path == "/v1/dnc/machine/delete" and method == "POST":
        ok, error = delete_machine(body.get("id"))
        if not ok:
            raise ValueError(error)
        return {"ok": True}
    if path == "/v1/dnc/machine/select" and method == "POST":
        if not get_machine(body.get("id")):
            raise ValueError("Máquina no encontrada")
        state.select_machine(body["id"])
        return {"ok": True}
    if path == "/v1/dnc/device/select" and method == "POST":
        return {"ok": True, "deprecated": True}
    if path == "/v1/dnc/transfer/status" and method == "GET":
        return state.snapshot()["transfer"]
    if path == "/v1/dnc/send" and method == "POST":
        machine = get_machine(body.get("machine_id") or state.snapshot()["active_machine_id"])
        if not machine:
            raise ValueError("Selecciona una máquina de este equipo")
        handler.controller.send(body.get("path", ""), machine)
        return {"ok": True}
    if path == "/v1/dnc/send/cancel" and method == "POST":
        import serial_transfer
        serial_transfer.request_cancel()
        return {"ok": True}
    repository = RuntimeSettings.load().repository()
    if path == "/v1/programs" and method == "GET":
        return repository.list(relative)
    if path == "/v1/programs/content" and method == "GET":
        return repository.read(relative)
    if path == "/v1/programs/content" and method == "PUT":
        return repository.write(body["path"], body["content"], body.get("expected_modified"))
    if path == "/v1/programs/content" and method == "DELETE":
        return repository.delete(relative)
    if path == "/v1/programs" and method == "POST":
        if body.get("kind", "file") == "directory":
            # Local directory creation is the only non-protocol extension.
            if not hasattr(repository, "_resolve"):
                raise ValueError("Crea la carpeta en el servidor de programas")
            name = body["name"].strip()
            if not name or name.startswith(".") or "/" in name or "\\" in name:
                raise ValueError("Nombre inválido")
            target = repository._resolve(str(Path(body.get("directory", "")) / name))
            target.mkdir(parents=True, exist_ok=False)
            return {"ok": True, "path": repository._relative(target)}
        return repository.create(body.get("directory", ""), body["name"])
    if path == "/v1/programs/search" and method == "GET":
        results, folders = [], [""]
        needle = query.get("q", [""])[0].casefold()
        visited = set()
        while folders and len(visited) < 1000 and len(results) < 300:
            folder = folders.pop()
            if folder in visited:
                continue
            visited.add(folder)
            for entry in repository.list(folder)["entries"]:
                if needle in entry["name"].casefold():
                    results.append(entry)
                if entry["kind"] == "directory":
                    folders.append(entry["path"])
        return {"results": results[:300]}
    if path == "/v1/changes" and method == "GET":
        # Monotonic wall clock supports polling clients across process restarts.
        import time
        version = time.time_ns()
        return {"version": version, "changed": version > int(query.get("since", ["0"])[0])}
    raise ValueError("Ruta no encontrada")
