"""Authenticated, asynchronous update jobs for devices without a screen."""
from __future__ import annotations

import fcntl
import json
import os
import subprocess
import threading
import time
import uuid
from pathlib import Path

from . import updater as u
from .operation_guard import transfer_active, Busy

POLICY_PATH = Path(os.environ.get("ZEUZ_UPDATE_POLICY", "/var/lib/zeuz/update-policy.json"))
JOB_LOCK = Path(os.environ.get("ZEUZ_UPDATE_JOB_LOCK", "/var/lib/zeuz/update-job.lock"))
BUSY_PHASES = {"checking", "downloading", "waiting_idle", "installing", "restarting"}


def read_policy():
    try: value = json.loads(POLICY_PATH.read_text())
    except (FileNotFoundError, ValueError): value = {}
    return {"auto_install": value.get("auto_install") is True}


def save_policy(value):
    if set(value) != {"auto_install"} or not isinstance(value["auto_install"], bool):
        raise ValueError("Ajuste de actualización inválido")
    u._atomic_write(POLICY_PATH, json.dumps(value).encode())
    return value


class UpdateManager:
    def __init__(self):
        self.lock = threading.Lock()
        self.stop_event = threading.Event()
        self.worker = None
        self.scheduler = None

    def status(self):
        state = u.read_update_state()
        return {**state, **read_policy(), "supported": True, "repository": u.REPOSITORY,
                "phase": state.get("phase", "idle"), "transfer_active": transfer_active()}

    def _write(self, phase, **fields):
        state = u.read_update_state()
        state.update(phase=phase, **fields)
        return u._write_state(u.STATE_PATH, state)

    def check(self):
        previous = u.read_update_state()
        return self._launch(lambda: self._check(previous), "checking", request_id=None, failure_stage="")

    def _check(self, previous):
        result = u.check_for_update(state_path=u.STATE_PATH, version_path=u.VERSION_PATH, revision_path=u.REVISION_PATH)
        if (previous.get("latest_revision") == result.get("latest_revision")
                and previous.get("phase") in {"failed", "rolled_back"}
                and previous.get("request_id") and previous.get("failure_stage") != "checking"):
            result.update(phase=previous["phase"], error=previous.get("error", ""), request_id=previous.get("request_id"))
            u._write_state(u.STATE_PATH, result)

    def install(self, revision, request_id):
        try: uuid.UUID(str(request_id))
        except (ValueError, TypeError, AttributeError): raise ValueError("Identificador de solicitud inválido")
        with self.lock:
            state = u.read_update_state()
            if state.get("request_id") == request_id:
                return self.status()
            if not state.get("available") or revision != state.get("latest_revision"):
                raise Busy("La versión disponible cambió; vuelve a comprobarla")
        return self._launch(lambda: self._install(revision), "waiting_idle", request_id=request_id, downloaded_bytes=0, started_at=time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))

    def _launch(self, work, phase, **fields):
        with self.lock:
            if self.worker and self.worker.is_alive(): raise Busy("Ya hay una operación de actualización en curso")
            current = u.read_update_state()
            if current.get("phase") in {"installing", "restarting"}: raise Busy("El equipo está instalando; espera su reconexión")
            JOB_LOCK.parent.mkdir(parents=True, exist_ok=True)
            handle = JOB_LOCK.open("a+")
            try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                handle.close()
                raise Busy("Otra operación de actualización está en curso")
            self._write(phase, error="", progress=0, **fields)
            def run():
                try: work()
                except Exception as exc: self._write("failed", error=u.update_error(exc), failure_stage=phase)
                finally:
                    fcntl.flock(handle, fcntl.LOCK_UN)
                    handle.close()
            self.worker = threading.Thread(target=run, daemon=True, name="zeuz-update-job")
            self.worker.start()
        return self.status()

    def _install(self, revision):
        # A screen is never involved; leave active transfers entirely alone.
        while transfer_active():
            self._write("waiting_idle", error="Esperando a que termine el envío")
            if self.stop_event.wait(1): return
        state = u.read_update_state()
        if state.get("latest_revision") != revision: raise Busy("La revisión preparada cambió")
        self._write("downloading", error="")
        last = 0
        def progress(size):
            nonlocal last
            if size - last >= 1024 * 1024:
                last = size
                self._write("downloading", downloaded_bytes=size)
        # Download the selected immutable commit, not a newly moved branch head.
        state = u.download_update(u.read_update_state(), state_path=u.STATE_PATH, archive_path=u.ARCHIVE_PATH, progress=progress)
        self._write("waiting_idle", error="")
        while not self.stop_event.is_set():
            if transfer_active():
                if self.stop_event.wait(1): return
                continue
            subprocess.run(["/usr/bin/systemctl", "--no-block", "start", "zeuz-update-apply.service"],
                           check=True, capture_output=True, text=True, timeout=15)
            # The root service writes durable phases, then restarts this API.
            for _ in range(30):
                if self.stop_event.wait(1): return
                phase = u.read_update_state().get("phase")
                if phase in {"installing", "restarting", "succeeded", "rolled_back", "failed"}: return
            if transfer_active():
                continue
            raise RuntimeError("El instalador no confirmó el inicio; revisa el servicio de actualización")

    def recover_stale_job(self):
        JOB_LOCK.parent.mkdir(parents=True, exist_ok=True)
        with JOB_LOCK.open("a+") as handle:
            try: fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError: return
            state = u.read_update_state()
            if state.get("phase") in {"checking", "downloading", "waiting_idle"}:
                self._write("failed", error="La preparación se interrumpió. Puedes volver a intentar la actualización.")

    def start(self):
        if self.scheduler: return
        def monitor():
            # Stale download/check jobs were interrupted, never report them complete.
            self.recover_stale_job()
            next_check = 0.0
            while not self.stop_event.wait(10):
                state = u.read_update_state()
                if state.get("phase") in BUSY_PHASES: continue
                if time.monotonic() >= next_check:
                    try: self.check()
                    except Busy: pass
                    next_check = time.monotonic() + 6 * 3600
                    continue
                if read_policy()["auto_install"] and state.get("available") and state.get("phase") == "available" and not transfer_active():
                    try: self.install(state["latest_revision"], str(uuid.uuid4()))
                    except Busy: pass
        self.scheduler = threading.Thread(target=monitor, daemon=True, name="zeuz-update-monitor")
        self.scheduler.start()

    def stop(self): self.stop_event.set()


def dispatch(manager, method, path, body=None):
    body = body or {}
    action = path.rsplit("/", 1)[-1]
    if method == "GET" and action == "status": return manager.status()
    if method == "POST" and action == "check" and not body: return manager.check()
    if method == "POST" and action == "install" and set(body) == {"revision", "request_id"}:
        return manager.install(body["revision"], body["request_id"])
    if method == "POST" and action == "policy":
        save_policy(body)
        return manager.status()
    raise ValueError("Solicitud de actualización inválida")
