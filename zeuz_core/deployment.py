"""Privileged deployment from a pinned GitHub commit, with health-checked rollback."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

from . import updater as u
from .operation_guard import OperationLease, Busy

ROLLBACK_DIR = Path(os.environ.get("ZEUZ_ROLLBACK_DIR", "/var/lib/zeuz-update-rollback"))


def phase(name, **fields):
    value = u.read_update_state()
    value.update(phase=name, **fields)
    u._write_state(u.STATE_PATH, value)
    u._set_zeuz_owner(u.STATE_PATH)
    return value


def verify_source(state, archive_path):
    """Independently verify a staged artifact against the fixed repository as root.

    The unprivileged API's self-computed checksum is insufficient provenance.
    No request can choose a URL, repository, script or systemd unit.
    """
    revision = str(state.get("latest_revision", ""))
    if not re.fullmatch(r"[0-9a-f]{40}", revision):
        raise RuntimeError("Revisión inválida")
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", u.REPOSITORY):
        raise RuntimeError("Canal de actualización inválido")
    commit = u._fetch_json(f"https://api.github.com/repos/{u.REPOSITORY}/commits/{u.BRANCH}")
    if commit.get("sha") != revision:
        raise RuntimeError("El canal oficial cambió; vuelve a comprobar la actualización")
    version = u._fetch_text(f"https://raw.githubusercontent.com/{u.REPOSITORY}/{revision}/VERSION")
    if version != state.get("latest_version") or u._version_key(version) < u._version_key(u._read_text(u.VERSION_PATH, u.installed_version())):
        raise RuntimeError("La versión publicada no coincide o es anterior a la instalada")
    digest = hashlib.sha256()
    total = 0
    with urllib.request.urlopen(u._request(f"https://github.com/{u.REPOSITORY}/archive/{revision}.tar.gz"), timeout=30) as response, archive_path.open("wb") as output:
        if not response.geturl().startswith((f"https://github.com/{u.REPOSITORY}/", f"https://codeload.github.com/{u.REPOSITORY}/")):
            raise RuntimeError("Destino de descarga no autorizado")
        while True:
            block = response.read(1024 * 1024)
            if not block: break
            total += len(block)
            if total > u.MAX_ARCHIVE_BYTES: raise RuntimeError("Archivo demasiado grande")
            digest.update(block)
            output.write(block)
    if digest.hexdigest() != state.get("archive_sha256"):
        raise RuntimeError("El artefacto no coincide con la revisión verificada de GitHub")


def _systemctl(*args):
    subprocess.run(["/usr/bin/systemctl", *args], check=True, timeout=45, capture_output=True, text=True)


def _healthy(version, timeout=35):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen("http://127.0.0.1:5000/api/info", timeout=2) as response:
                info = json.load(response)
            if info.get("service") == "zeuz-dnc" and info.get("version") == version:
                return True
        except (OSError, ValueError):
            pass
        time.sleep(1)
    return False


def sync_tree(root):
    """Make the backup/code durable before removing the recovery marker."""
    for path in root.rglob("*"):
        if path.is_file():
            with path.open("rb") as handle: os.fsync(handle.fileno())
    for path in [p for p in root.rglob("*") if p.is_dir()] + [root]:
        descriptor = os.open(path, os.O_RDONLY)
        try: os.fsync(descriptor)
        finally: os.close(descriptor)


def snapshot():
    shutil.rmtree(ROLLBACK_DIR, ignore_errors=True)
    ROLLBACK_DIR.mkdir(mode=0o700, parents=True)
    shutil.copytree(u.INSTALL_DIR, ROLLBACK_DIR / "code")
    units = list(u.SYSTEMD_UNITS)
    for name, source in [("version", u.VERSION_PATH), ("revision", u.REVISION_PATH)] + [(unit, u.SYSTEMD_DIR / unit) for unit in units]:
        if source.exists(): shutil.copy2(source, ROLLBACK_DIR / name)
    sync_tree(ROLLBACK_DIR)
    # Write the completion marker only after a complete backup is durable.
    u._atomic_write(ROLLBACK_DIR / "ready", json.dumps({"units": units}).encode(), 0o600)


def restore_snapshot():
    if not (ROLLBACK_DIR / "ready").exists(): return False
    recovered = u.INSTALL_DIR.with_name(u.INSTALL_DIR.name + ".recover")
    shutil.rmtree(recovered, ignore_errors=True)
    shutil.copytree(ROLLBACK_DIR / "code", recovered)
    shutil.rmtree(u.INSTALL_DIR, ignore_errors=True)
    os.replace(recovered, u.INSTALL_DIR)
    for name, target in [("version", u.VERSION_PATH), ("revision", u.REVISION_PATH)] + [(unit, u.SYSTEMD_DIR / unit) for unit in u.SYSTEMD_UNITS]:
        saved = ROLLBACK_DIR / name
        if saved.exists(): u._atomic_write(target, saved.read_bytes(), 0o644)
        else: target.unlink(missing_ok=True)
    sync_tree(u.INSTALL_DIR)
    sync_tree(u.SYSTEMD_DIR)
    (ROLLBACK_DIR / "ready").unlink()
    return True


def apply_managed_update(*, verify=verify_source, systemctl=_systemctl, healthy=_healthy):
    touch_active = False
    value = u.read_update_state()
    if not value.get("downloaded"): raise RuntimeError("No hay una actualización preparada")
    try:
        lease = OperationLease(update=True)
    except Busy:
        return phase("waiting_idle", error="Esperando a que termine el envío")
    with lease:
        try:
            phase("installing", error="")
            # Never extract the mutable file staged by the unprivileged API.
            import tempfile
            with tempfile.TemporaryDirectory(prefix=".zeuz-verified-", dir=u.INSTALL_DIR.parent) as scratch:
                private = Path(scratch)
                verify(value, private / "update.tar.gz")
                u._write_state(private / "state.json", value)
                try:
                    systemctl("is-active", "--quiet", "zeuz-dnc-qt.service")
                    touch_active = True
                except subprocess.CalledProcessError:
                    pass
                return _install_verified(value, private, systemctl, healthy, touch_active)
        except Exception as exc:
            rolled_back = False
            if (ROLLBACK_DIR / "ready").exists():
                try: systemctl("stop", "zeuz-dnc-api.service")
                except Exception: pass
                try:
                    rolled_back = restore_snapshot()
                    systemctl("daemon-reload")
                    systemctl("start", "zeuz-dnc-api.service")
                    if touch_active: systemctl("start", "zeuz-dnc-qt.service")
                except Exception as recovery_error:
                    rolled_back = False
                    exc = RuntimeError(f"{exc}; recuperación pendiente: {recovery_error}")
            restored_version = u._read_text(u.VERSION_PATH, u.installed_version())
            restored_revision = u._read_text(u.REVISION_PATH)
            return phase("rolled_back" if rolled_back else "failed", current_version=restored_version,
                         current_revision=restored_revision, downloaded=False, available=True, error=str(exc)[:500])


def _install_verified(value, private, systemctl, healthy, touch_active):
    snapshot()
    try:
        systemctl("stop", "zeuz-dnc-api.service")
        if touch_active: systemctl("stop", "zeuz-dnc-qt.service")
        installed = u.apply_downloaded_update(state_path=private / "state.json", archive_path=private / "update.tar.gz",
            install_dir=u.INSTALL_DIR, version_path=u.VERSION_PATH, revision_path=u.REVISION_PATH, systemd_dir=u.SYSTEMD_DIR)
        phase("restarting", **{k: v for k, v in installed.items() if k != "phase"})
        systemctl("daemon-reload")
        systemctl("start", "zeuz-dnc-api.service")
        if touch_active: systemctl("start", "zeuz-dnc-qt.service")
        sync_tree(u.INSTALL_DIR)
        sync_tree(u.SYSTEMD_DIR)
        if not healthy(value["latest_version"]):
            raise RuntimeError("La nueva API no respondió correctamente; se restaura la versión anterior")
        (ROLLBACK_DIR / "ready").unlink(missing_ok=True)
        return phase("succeeded", progress=100, error="", completed_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    except Exception:
        # The outer handler restores code, units and version before restarting.
        if touch_active:
            try: systemctl("stop", "zeuz-dnc-qt.service")
            except Exception: pass
        raise
