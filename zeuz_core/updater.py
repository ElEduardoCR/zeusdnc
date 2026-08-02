from __future__ import annotations

import argparse
import hashlib
import json
import os
import pwd
import shutil
import tarfile
import tempfile
import time
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Callable

from .version import installed_version


REPOSITORY = os.environ.get("ZEUZ_UPDATE_REPOSITORY", "ElEduardoCR/zeusdnc")
BRANCH = os.environ.get("ZEUZ_UPDATE_BRANCH", "main")
STATE_PATH = Path(os.environ.get("ZEUZ_UPDATE_STATE", "/var/lib/zeuz/update.json"))
ARCHIVE_PATH = Path(os.environ.get("ZEUZ_UPDATE_ARCHIVE", "/var/lib/zeuz/update.tar.gz"))
REVISION_PATH = Path(os.environ.get("ZEUZ_REVISION_PATH", "/etc/zeuz/revision"))
VERSION_PATH = Path(os.environ.get("ZEUZ_VERSION_PATH", "/etc/zeuz/version"))
INSTALL_DIR = Path(os.environ.get("ZEUZ_INSTALL_DIR", "/opt/zeuz/zeusdnc"))
SYSTEMD_DIR = Path(os.environ.get("ZEUZ_SYSTEMD_DIR", "/etc/systemd/system"))
MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_EXTRACTED_BYTES = 250 * 1024 * 1024

SYSTEMD_UNITS = (
    "zeuz-dnc-qt.service",
    "zeuz-dnc-api.service",
    "zeuz-update-check.service",
    "zeuz-update-apply.service",
)


def _version_key(value: str) -> tuple[int, ...]:
    clean = value.strip().lstrip("vV")
    parts = clean.split(".")
    if not parts or any(not part.isdigit() for part in parts):
        raise ValueError(f"Versión inválida en GitHub: {value}")
    return tuple(int(part) for part in parts)


def _read_text(path: Path, fallback: str = "") -> str:
    try:
        return path.read_text(encoding="utf-8").strip()
    except OSError:
        return fallback


def _atomic_write(path: Path, content: bytes, mode: int = 0o640) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    with temporary.open("wb") as handle:
        handle.write(content)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)


def _write_state(path: Path, state: dict) -> dict:
    payload = (json.dumps(state, ensure_ascii=False, indent=2) + "\n").encode("utf-8")
    _atomic_write(path, payload)
    return state


def read_update_state(path: Path = STATE_PATH) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        value = {}
    return {
        "available": bool(value.get("available", False)),
        "current_version": str(value.get("current_version", installed_version())),
        "current_revision": str(value.get("current_revision", "")),
        "latest_version": str(value.get("latest_version", "")),
        "latest_revision": str(value.get("latest_revision", "")),
        "checked_at": str(value.get("checked_at", "")),
        "downloaded": bool(value.get("downloaded", False)),
        "error": str(value.get("error", "")),
    }


def _request(url: str):
    return urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": f"ZeuzDNC-Updater/{installed_version()}",
            "X-GitHub-Api-Version": "2022-11-28",
        },
    )


def _fetch_json(url: str) -> dict:
    with urllib.request.urlopen(_request(url), timeout=15) as response:
        value = json.loads(response.read().decode("utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError("GitHub devolvió una respuesta inesperada")
    return value


def _fetch_text(url: str) -> str:
    with urllib.request.urlopen(_request(url), timeout=15) as response:
        return response.read(4096).decode("utf-8").strip()


def check_for_update(
    *,
    state_path: Path = STATE_PATH,
    version_path: Path = VERSION_PATH,
    revision_path: Path = REVISION_PATH,
    fetch_json: Callable[[str], dict] = _fetch_json,
    fetch_text: Callable[[str], str] = _fetch_text,
) -> dict:
    current_version = _read_text(version_path, installed_version())
    current_revision = _read_text(revision_path, f"image-{current_version}")
    commit = fetch_json(f"https://api.github.com/repos/{REPOSITORY}/commits/{BRANCH}")
    revision = str(commit.get("sha", "")).strip().lower()
    if len(revision) != 40 or any(character not in "0123456789abcdef" for character in revision):
        raise RuntimeError("GitHub no devolvió una revisión válida")
    latest_version = fetch_text(
        f"https://raw.githubusercontent.com/{REPOSITORY}/{revision}/VERSION"
    ).strip()
    current_key = _version_key(current_version)
    latest_key = _version_key(latest_version)
    available = latest_key > current_key or (
        latest_key == current_key and revision != current_revision
    )
    state = {
        "available": available,
        "current_version": current_version,
        "current_revision": current_revision,
        "latest_version": latest_version,
        "latest_revision": revision,
        "checked_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "downloaded": False,
        "error": "" if latest_key >= current_key else "GitHub contiene una versión anterior",
    }
    if latest_key < current_key:
        state["available"] = False
    return _write_state(state_path, state)


def safe_check_for_update(**kwargs) -> dict:
    state_path = kwargs.get("state_path", STATE_PATH)
    try:
        return check_for_update(**kwargs)
    except Exception as exc:  # noqa: BLE001 - se muestra en la interfaz
        previous = read_update_state(state_path)
        previous.update(
            checked_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            error=str(exc)[:300],
        )
        return _write_state(state_path, previous)


def download_update(
    state: dict | None = None,
    *,
    state_path: Path = STATE_PATH,
    archive_path: Path = ARCHIVE_PATH,
) -> dict:
    state = dict(state or read_update_state(state_path))
    if not state.get("available"):
        raise RuntimeError("No hay una actualización nueva disponible")
    revision = str(state.get("latest_revision", ""))
    if len(revision) != 40:
        raise RuntimeError("La revisión de actualización es inválida")
    url = f"https://github.com/{REPOSITORY}/archive/{revision}.tar.gz"
    archive_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = archive_path.with_name(archive_path.name + ".part")
    digest = hashlib.sha256()
    size = 0
    try:
        with urllib.request.urlopen(_request(url), timeout=30) as response, temporary.open(
            "wb"
        ) as output:
            while True:
                block = response.read(1024 * 1024)
                if not block:
                    break
                size += len(block)
                if size > MAX_ARCHIVE_BYTES:
                    raise RuntimeError("La actualización supera el tamaño permitido")
                digest.update(block)
                output.write(block)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, archive_path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    state.update(downloaded=True, archive_sha256=digest.hexdigest(), archive_size=size)
    return _write_state(state_path, state)


def prepare_update() -> dict:
    state = check_for_update()
    return download_update(state)


def _validated_members(archive: tarfile.TarFile) -> tuple[list[tarfile.TarInfo], str]:
    members = archive.getmembers()
    if not members:
        raise RuntimeError("La actualización está vacía")
    roots: set[str] = set()
    total = 0
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise RuntimeError("La actualización contiene una ruta insegura")
        if member.issym() or member.islnk() or member.isdev():
            raise RuntimeError("La actualización contiene enlaces o dispositivos no permitidos")
        roots.add(path.parts[0])
        total += max(0, member.size)
        if total > MAX_EXTRACTED_BYTES:
            raise RuntimeError("La actualización descomprimida supera el tamaño permitido")
    if len(roots) != 1:
        raise RuntimeError("La actualización no tiene una raíz única")
    return members, roots.pop()


def _set_zeuz_owner(path: Path) -> None:
    try:
        account = pwd.getpwnam("zeuz")
        os.chown(path, account.pw_uid, account.pw_gid)
    except (KeyError, PermissionError, OSError):
        pass


def apply_downloaded_update(
    *,
    state_path: Path = STATE_PATH,
    archive_path: Path = ARCHIVE_PATH,
    install_dir: Path = INSTALL_DIR,
    version_path: Path = VERSION_PATH,
    revision_path: Path = REVISION_PATH,
    systemd_dir: Path | None = SYSTEMD_DIR,
) -> dict:
    state = read_update_state(state_path)
    if not state.get("available") or not state.get("downloaded"):
        raise RuntimeError("No existe una actualización descargada y lista")
    expected_hash = ""
    try:
        raw_state = json.loads(state_path.read_text(encoding="utf-8"))
        expected_hash = str(raw_state.get("archive_sha256", ""))
    except (OSError, json.JSONDecodeError):
        pass
    archive_digest = hashlib.sha256()
    with archive_path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            archive_digest.update(block)
    digest = archive_digest.hexdigest()
    if not expected_hash or digest != expected_hash:
        raise RuntimeError("El checksum de la actualización no coincide")

    work_parent = install_dir.parent
    work_parent.mkdir(parents=True, exist_ok=True)
    temporary_root = Path(tempfile.mkdtemp(prefix=".zeuz-update-", dir=work_parent))
    staging = install_dir.with_name(install_dir.name + ".new")
    backup = install_dir.with_name(install_dir.name + ".previous")
    moved_current = False
    installed_new = False
    try:
        with tarfile.open(archive_path, "r:gz") as archive:
            members, root_name = _validated_members(archive)
            archive.extractall(temporary_root, members=members, filter="data")
        source = temporary_root / root_name
        required = ("VERSION", "qt_app", "zeuz_core", "machines.py", "systemd")
        missing = [name for name in required if not (source / name).exists()]
        if missing:
            raise RuntimeError("La actualización está incompleta: " + ", ".join(missing))
        candidate_version = (source / "VERSION").read_text(encoding="utf-8").strip()
        if candidate_version != state["latest_version"]:
            raise RuntimeError("La versión descargada no coincide con la publicada")

        shutil.rmtree(staging, ignore_errors=True)
        shutil.copytree(source, staging)
        for path in staging.rglob("*"):
            try:
                path.chmod(path.stat().st_mode | 0o044)
            except OSError:
                continue

        if systemd_dir is not None:
            systemd_dir.mkdir(parents=True, exist_ok=True)
            for unit in SYSTEMD_UNITS:
                source_unit = staging / "systemd" / unit
                if not source_unit.exists():
                    raise RuntimeError(f"Falta la unidad de sistema {unit}")
                destination = systemd_dir / unit
                _atomic_write(destination, source_unit.read_bytes(), mode=0o644)

        shutil.rmtree(backup, ignore_errors=True)
        if install_dir.exists():
            os.replace(install_dir, backup)
            moved_current = True
        os.replace(staging, install_dir)
        installed_new = True
        _atomic_write(version_path, (candidate_version + "\n").encode("utf-8"), 0o644)
        revision = state["latest_revision"]
        _atomic_write(revision_path, (revision + "\n").encode("ascii"), 0o644)

        state.update(
            available=False,
            downloaded=False,
            current_version=candidate_version,
            current_revision=revision,
            error="",
            installed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        )
        _write_state(state_path, state)
        _set_zeuz_owner(state_path)
        archive_path.unlink(missing_ok=True)
        return state
    except Exception:
        if installed_new and install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)
        if moved_current and backup.exists():
            os.replace(backup, install_dir)
        raise
    finally:
        shutil.rmtree(staging, ignore_errors=True)
        shutil.rmtree(temporary_root, ignore_errors=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="Actualizador de Zeuz DNC")
    action = parser.add_mutually_exclusive_group(required=True)
    action.add_argument("--check", action="store_true")
    action.add_argument("--download", action="store_true")
    action.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if args.check:
        print(json.dumps(safe_check_for_update(), ensure_ascii=False))
    elif args.download:
        print(json.dumps(prepare_update(), ensure_ascii=False))
    else:
        print(json.dumps(apply_downloaded_update(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
