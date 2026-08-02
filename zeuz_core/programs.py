from __future__ import annotations

import json
import os
import tempfile
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol


class ProgramSourceError(Exception):
    pass


class ProgramRepository(Protocol):
    def list(self, path: str = "") -> dict: ...

    def read(self, path: str) -> dict: ...

    def write(self, path: str, content: str, expected_modified: float | None = None) -> dict: ...

    def create(self, directory: str, name: str) -> dict: ...

    def delete(self, path: str) -> dict: ...

    def materialize(self, path: str) -> Path: ...


@dataclass(frozen=True)
class AgentConnection:
    base_url: str
    token: str
    timeout: float = 10.0

    @property
    def normalized_url(self) -> str:
        return self.base_url.rstrip("/")


class AgentProgramRepository:
    """Cliente del contrato HTTP v1 expuesto por Zeuz Agent."""

    def __init__(self, connection: AgentConnection) -> None:
        self.connection = connection

    def _request(self, method: str, endpoint: str, body: dict | None = None) -> dict:
        url = self.connection.normalized_url + endpoint
        data = None
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.connection.token}",
        }
        if body is not None:
            data = json.dumps(body, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        request = urllib.request.Request(url, data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.connection.timeout) as response:
                payload = json.load(response)
        except urllib.error.HTTPError as exc:
            try:
                payload = json.load(exc)
                detail = payload.get("error", str(exc))
            except Exception:
                detail = str(exc)
            raise ProgramSourceError(detail) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise ProgramSourceError(
                f"No se pudo contactar Zeuz Agent en {self.connection.normalized_url}"
            ) from exc
        if isinstance(payload, dict) and payload.get("ok") is False:
            raise ProgramSourceError(str(payload.get("error", "Zeuz Agent rechazó la operación")))
        return payload

    @staticmethod
    def _query(path: str) -> str:
        return urllib.parse.urlencode({"path": path})

    def list(self, path: str = "") -> dict:
        return self._request("GET", f"/v1/programs?{self._query(path)}")

    def read(self, path: str) -> dict:
        return self._request("GET", f"/v1/programs/content?{self._query(path)}")

    def write(self, path: str, content: str, expected_modified: float | None = None) -> dict:
        body: dict = {"path": path, "content": content}
        if expected_modified is not None:
            body["expected_modified"] = expected_modified
        return self._request("PUT", "/v1/programs/content", body)

    def create(self, directory: str, name: str) -> dict:
        return self._request(
            "POST",
            "/v1/programs",
            {"directory": directory, "name": name, "kind": "file"},
        )

    def delete(self, path: str) -> dict:
        return self._request("DELETE", f"/v1/programs/content?{self._query(path)}")

    def materialize(self, path: str) -> Path:
        url = (
            self.connection.normalized_url
            + f"/v1/programs/download?{self._query(path)}"
        )
        request = urllib.request.Request(
            url,
            headers={"Authorization": f"Bearer {self.connection.token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.connection.timeout) as response:
                payload = response.read()
        except urllib.error.HTTPError as exc:
            try:
                detail = json.load(exc).get("error", str(exc))
            except Exception:
                detail = str(exc)
            raise ProgramSourceError(detail) from exc
        except (OSError, urllib.error.URLError) as exc:
            raise ProgramSourceError("No se pudo descargar el programa desde Zeuz Agent") from exc
        suffix = Path(path).suffix or ".nc"
        descriptor, name = tempfile.mkstemp(prefix="zeuz-send-", suffix=suffix)
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(payload)
        return Path(name)


class LocalProgramRepository:
    """Fuente local para dispositivos que guardan los programas en Zeuz."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative: str, *, exists: bool = False) -> Path:
        raw = (relative or "").strip().replace("\\", "/").lstrip("/")
        if ".." in Path(raw).parts:
            raise ProgramSourceError("Ruta inválida")
        target = (self.root / raw).resolve(strict=False)
        try:
            target.relative_to(self.root)
        except ValueError as exc:
            raise ProgramSourceError("Ruta inválida") from exc
        if exists and not target.exists():
            raise ProgramSourceError("Programa o carpeta no encontrado")
        return target

    def _relative(self, path: Path) -> str:
        value = path.relative_to(self.root).as_posix()
        return "" if value == "." else value

    def list(self, path: str = "") -> dict:
        directory = self._resolve(path, exists=True)
        if not directory.is_dir():
            raise ProgramSourceError("Carpeta no encontrada")
        entries = []
        for child in sorted(directory.iterdir(), key=lambda item: (not item.is_dir(), item.name.casefold())):
            if child.name.startswith(".") or child.name in {"Thumbs.db", "desktop.ini"}:
                continue
            try:
                child.resolve().relative_to(self.root)
                stat = child.stat()
            except (OSError, ValueError):
                continue
            entries.append(
                {
                    "name": child.name,
                    "path": self._relative(child),
                    "kind": "directory" if child.is_dir() else "file",
                    "size": 0 if child.is_dir() else stat.st_size,
                    "modified": stat.st_mtime,
                }
            )
        current = self._relative(directory)
        parent = None if not current else Path(current).parent.as_posix()
        if parent == ".":
            parent = ""
        return {"path": current, "parent": parent, "entries": entries, "version": 0}

    def read(self, path: str) -> dict:
        target = self._resolve(path, exists=True)
        if not target.is_file():
            raise ProgramSourceError("Programa no encontrado")
        raw = target.read_bytes()
        if b"\x00" in raw[:4096]:
            raise ProgramSourceError("El archivo no es texto CNC compatible")
        stat = target.stat()
        return {
            "name": target.name,
            "path": self._relative(target),
            "content": raw.decode("latin-1"),
            "truncated": False,
            "size": stat.st_size,
            "modified": stat.st_mtime,
        }

    def write(self, path: str, content: str, expected_modified: float | None = None) -> dict:
        target = self._resolve(path)
        if expected_modified is not None and target.exists():
            if abs(target.stat().st_mtime - expected_modified) > 0.000001:
                raise ProgramSourceError("El programa cambió; vuelve a abrirlo antes de guardar")
        target.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(prefix=".zeuz-", dir=target.parent)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(content.encode("latin-1", errors="replace"))
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_name, target)
        except OSError:
            try:
                os.unlink(temp_name)
            except OSError:
                pass
            raise
        stat = target.stat()
        return {"ok": True, "path": self._relative(target), "modified": stat.st_mtime}

    def create(self, directory: str, name: str) -> dict:
        name = name.strip()
        if not name or name.startswith(".") or "/" in name or "\\" in name:
            raise ProgramSourceError("Nombre inválido")
        target = self._resolve((Path(directory) / name).as_posix())
        if target.exists():
            raise ProgramSourceError("Ya existe un programa con ese nombre")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch(exist_ok=False)
        return {"ok": True, "path": self._relative(target)}

    def delete(self, path: str) -> dict:
        target = self._resolve(path, exists=True)
        if not target.is_file():
            raise ProgramSourceError("Programa no encontrado")
        target.unlink()
        return {"ok": True}

    def materialize(self, path: str) -> Path:
        target = self._resolve(path, exists=True)
        if not target.is_file():
            raise ProgramSourceError("Programa no encontrado")
        return target
