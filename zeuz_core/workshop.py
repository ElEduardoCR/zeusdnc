"""Persistent workshop identity, byte-preserving program mirror and remote access.

The PC publishes additions/updates only. Replaced bytes are archived; deletions
are intentionally not mirrored. Machine synchronization uses conditional writes.
"""
from __future__ import annotations

import base64
import hashlib
import json
import os
import tempfile
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from zeuz_core.programs import LocalProgramRepository, ProgramSourceError, program_lock

_lock = threading.RLock()


def settings_path() -> Path:
    from zeuz_core.settings import DEFAULT_SETTINGS_PATH
    return DEFAULT_SETTINGS_PATH.with_name("workshop.json")


def settings() -> dict:
    try:
        return json.loads(settings_path().read_text())
    except FileNotFoundError:
        return {}


def configure(changes: dict) -> dict:
    with _lock:
        value = settings()
        if "name" in changes:
            name = str(changes["name"]).strip()
            if not name or len(name) > 80:
                raise ValueError("Usa un nombre de 1 a 80 caracteres")
            value["name"] = name
        if "program_server" in changes:
            url = str(changes["program_server"]).strip().rstrip("/")
            if url and (urlsplit(url).scheme != "http" or not urlsplit(url).hostname):
                raise ValueError("Servidor de programas inválido")
            value["program_server"] = url
        if "mobile_token" in changes:
            token = str(changes["mobile_token"])
            if len(token) < 16:
                raise ValueError("Credencial de taller inválida")
            value["mobile_token"] = token
        if "machine_routes" in changes:
            routes = changes["machine_routes"]
            if not isinstance(routes, list):
                raise ValueError("Rutas de máquinas inválidas")
            for route in routes:
                if not isinstance(route, dict) or not str(route.get("host", "")).strip() or not 1 <= int(route.get("port", 0)) <= 65535:
                    raise ValueError("Ruta de máquina inválida")
            value["machine_routes"] = routes
        atomic_write(settings_path(), json.dumps(value, ensure_ascii=False).encode())
        return value


def atomic_write(path: Path, raw: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp = tempfile.mkstemp(prefix=".zeuz-", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        if os.path.exists(temp):
            os.unlink(temp)


def local_repository() -> LocalProgramRepository:
    from zeuz_core.settings import RuntimeSettings
    return LocalProgramRepository(Path(RuntimeSettings.load().local_path))


def mirror_program(body: dict) -> dict:
    repository = local_repository()
    path = str(body.get("path", ""))
    if not path or any(part.startswith(".") for part in Path(path).parts):
        raise ValueError("Ruta de programa inválida")
    target = repository._resolve(path)
    raw = base64.b64decode(body["data"], validate=True)
    digest = hashlib.sha256(raw).hexdigest()
    if digest != body.get("sha256"):
        raise ValueError("El archivo llegó incompleto")
    with program_lock(repository.root):
        if target.exists():
            previous = target.read_bytes()
            old_hash = hashlib.sha256(previous).hexdigest()
            if previous == raw:
                return {"ok": True, "sha256": digest}
            # Content-addressed backups are idempotent across interrupted retries.
            backup = repository.root / ".zeuz-history" / old_hash
            if not backup.exists():
                atomic_write(backup, previous)
            record = repository.root / ".zeuz-history" / (hashlib.sha256(path.encode()).hexdigest() + ".json")
            history = json.loads(record.read_text()) if record.exists() else {"path": path, "versions": []}
            if old_hash not in history["versions"]:
                history["versions"].append(old_hash)
                atomic_write(record, json.dumps(history).encode())
        atomic_write(target, raw)
    return {"ok": True, "sha256": digest}


def dispatch(method: str, target: str, body: dict | None = None):
    """Return a JSON value for /api/workshop; no serial side effects."""
    from machines import load_machines, sync_machine
    parsed = urlsplit(target)
    query = parse_qs(parsed.query)
    path = query.get("path", [""])[0]
    body = body or {}
    if parsed.path == "/api/workshop/info" and method == "GET":
        from zeuz_core.mobile_api import credentials
        value = credentials()
        return {"ok": True, "api": 1, "hostname": os.uname().nodename, **{key: item for key, item in value.items() if key not in {"mobile_token", "pairing_code"}}}
    if parsed.path == "/api/workshop/configure" and method == "POST":
        return {"ok": True, **{key: item for key, item in configure(body).items() if key not in {"mobile_token", "pairing_code"}}}
    if parsed.path == "/api/workshop/machines" and method == "GET":
        return load_machines()
    if parsed.path == "/api/workshop/machine" and method == "POST":
        return {"ok": True, "machine": sync_machine(body)}
    if parsed.path == "/api/workshop/mirror" and method == "POST":
        return mirror_program(body)
    repository = local_repository()
    if parsed.path == "/api/workshop/manifest" and method == "GET":
        return {p.relative_to(repository.root).as_posix(): p.stat().st_size for p in repository.root.rglob("*") if p.is_file() and not p.is_symlink() and p.resolve().is_relative_to(repository.root) and not any(part.startswith(".") for part in p.relative_to(repository.root).parts)}
    if parsed.path == "/api/workshop/programs" and method == "GET":
        return repository.list(path)
    if parsed.path == "/api/workshop/content" and method == "GET":
        return repository.read(path)
    if parsed.path == "/api/workshop/bytes" and method == "GET":
        return {"data": base64.b64encode(repository.materialize(path).read_bytes()).decode()}
    if parsed.path == "/api/workshop/content" and method == "PUT":
        return repository.write(body["path"], body["content"], body.get("expected_modified"))
    if parsed.path == "/api/workshop/programs" and method == "POST":
        if body.get("kind", "file") == "directory":
            name = body["name"].strip()
            if not name or name.startswith(".") or "/" in name or "\\" in name:
                raise ValueError("Nombre inválido")
            target = repository._resolve(str(Path(body.get("directory", "")) / name))
            target.mkdir(parents=True, exist_ok=False)
            return {"ok": True, "path": repository._relative(target)}
        return repository.create(body.get("directory", ""), body["name"])
    if parsed.path == "/api/workshop/content" and method == "DELETE":
        return repository.delete(path)
    raise ValueError("Ruta de taller no encontrada")
