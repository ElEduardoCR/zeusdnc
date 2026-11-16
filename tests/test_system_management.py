"""Clock repairs use only temporary files and an injected clock setter."""
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
import sys
from unittest.mock import Mock, patch
import urllib.error
import urllib.request
import uuid

from zeuz_core import system_management as system, operation_guard, update_auth, remote_updates, updater
sys.modules.setdefault("serial_transfer", Mock())
from zeuz_core.headless_api import Server, HeadlessController

spec = importlib.util.spec_from_file_location("clock_runner_test", Path(__file__).parents[1] / "packaging/clock_runner.py")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)

OLD = 1751569200  # 2025-07-03
NOW = 1794596400  # 2026-11-13
BOOT = str(uuid.uuid4())


class ClockFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.request = self.root / "inbox/request.json"
        self.results = self.root / "results.json"
        self.lock = self.root / "operation.lock"
        for directory in ("inbox", "etc", "var/lib/systemd/timesync"):
            (self.root / directory).mkdir(parents=True, exist_ok=True)
        self.lock.touch()
        (self.root / "etc/fake-hwclock.data").write_text("2025-07-03 19:00:00\n")
        (self.root / "var/lib/systemd/timesync/clock").touch()
        self.value = {"request_id": str(uuid.uuid4()), "utc_unix": NOW, "monotonic": 100.0, "boot_id": BOOT}
        self.request.write_text(json.dumps(self.value))
        self.setter = Mock()
        # A mistaken test call to the real host setter must fail loudly.
        guard = patch.object(time, "clock_settime", side_effect=AssertionError("Host clock must never change"), create=True)
        guard.start()
        self.addCleanup(guard.stop)

    def execute(self, **changes):
        args = dict(request_path=self.request, results_path=self.results, lock_path=self.lock,
                    filesystem_root=self.root, current=lambda: OLD, monotonic=lambda: 102.0,
                    boot_id=BOOT, owner=os.getuid(), set_clock=self.setter)
        args.update(changes)
        return runner.execute(**args)


class ClockRunnerTests(ClockFixture):
    def test_success_persists_both_clocks_and_duplicate_never_sets_again(self):
        result = self.execute()
        self.assertEqual(result["phase"], "succeeded")
        self.setter.assert_called_once_with(NOW + 2)
        self.assertEqual((self.root / "etc/fake-hwclock.data").read_text(),
                         time.strftime("%Y-%m-%d %H:%M:%S\n", time.gmtime(NOW + 2)))
        self.assertEqual(int((self.root / "var/lib/systemd/timesync/clock").stat().st_mtime), NOW + 2)
        self.assertEqual(self.execute(monotonic=lambda: 10000, boot_id="new-boot"), result)
        self.assertEqual(self.setter.call_count, 1)
        self.request.write_text(json.dumps({**self.value, "utc_unix": NOW + 10}))
        with self.assertRaisesRegex(ValueError, "identificador"):
            self.execute()

    def test_invalid_timestamp_freshness_boot_and_extra_commands_are_rejected(self):
        variants = [{"utc_unix": True}, {"utc_unix": "2026"}, {"utc_unix": 0},
                    {"utc_unix": runner.MAX_UTC}, {"utc_unix": OLD - 305},
                    {"utc_unix": OLD + runner.MAX_FORWARD + 1}, {"monotonic": float("nan")},
                    {"monotonic": 103.0}, {"monotonic": 42.0}, {"boot_id": "another-boot"},
                    {"request_id": "not-a-uuid"}, {"command": "date"}]
        for change in variants:
            with self.subTest(change=change):
                self.results.unlink(missing_ok=True)
                self.request.write_text(json.dumps({**self.value, **change}))
                self.assertEqual(self.execute()["phase"], "failed")
        self.setter.assert_not_called()

    def test_active_transfer_prevents_clock_change(self):
        with self.lock.open("r+") as active:
            fcntl.flock(active, fcntl.LOCK_SH | fcntl.LOCK_NB)
            result = self.execute()
        self.assertEqual(result["phase"], "failed")
        self.assertIn("envío", result["error"])
        self.setter.assert_not_called()

    def test_symlink_oversize_nonregular_and_wrong_owner_requests_are_rejected(self):
        original = self.root / "original.json"
        self.request.replace(original)
        self.request.symlink_to(original)
        with self.assertRaises(OSError): self.execute()
        self.request.unlink()
        self.request.write_bytes(b"x" * 2049)
        with self.assertRaises(ValueError): self.execute()
        self.request.unlink()
        os.mkfifo(self.request)
        with self.assertRaises(ValueError): self.execute()
        self.request.unlink()
        self.request.write_text(json.dumps(self.value))
        with self.assertRaises(ValueError): self.execute(owner=os.getuid() + 1)
        self.setter.assert_not_called()

    def test_missing_lock_or_symlink_persistent_clock_never_changes_time(self):
        self.lock.unlink()
        self.assertEqual(self.execute()["phase"], "failed")
        self.results.unlink()
        self.lock.touch()
        fake = self.root / "etc/fake-hwclock.data"
        fake.unlink()
        fake.symlink_to(self.request)
        self.assertEqual(self.execute()["phase"], "failed")
        self.setter.assert_not_called()

    def test_result_history_stays_bounded(self):
        history = [{"request_id": str(uuid.uuid4()), "requested_utc": NOW, "phase": "failed", "error": "old"}
                   for _ in range(32)]
        self.results.write_text(json.dumps(history))
        self.assertEqual(self.execute()["phase"], "succeeded")
        saved = json.loads(self.results.read_text())
        self.assertEqual(len(saved), 32)
        self.assertEqual(saved[-1]["request_id"], self.value["request_id"])

    def test_invalid_request_cannot_expand_result_history_with_untrusted_fields(self):
        self.request.write_text(json.dumps({**self.value, "request_id": "x" * 1000, "utc_unix": {"ignored": "x" * 100}}))
        self.assertEqual(self.execute()["phase"], "failed")
        self.assertLess(self.results.stat().st_size, 500)
        self.setter.assert_not_called()


class SystemAPITests(ClockFixture):
    def setUp(self):
        super().setUp()
        self.request.unlink()
        self.boot_file = self.root / "boot_id"
        self.boot_file.write_text(BOOT)
        self.helper = self.root / "clock_runner.py"
        self.helper.touch()
        self.log = self.root / "transfer-errors.log"
        runtime = self.root / "runtime.json"
        runtime.write_text(json.dumps({"paired_agent": {"token": "owner"}}))
        replacements = [(system, "REQUEST_PATH", self.request), (system, "RESULTS_PATH", self.results),
                        (system, "RUNNER_PATH", self.helper), (system, "BOOT_ID_PATH", self.boot_file),
                        (system, "LOG_PATH", self.log), (operation_guard, "LOCK_PATH", self.lock),
                        (update_auth, "DEFAULT_SETTINGS_PATH", runtime)]
        for module, name, value in replacements:
            item = patch.object(module, name, value)
            item.start()
            self.addCleanup(item.stop)
        snapshot = patch("serial_transfer.get_serial_diagnostics", return_value={"phase": "idle", "port_open": False})
        self.serial_snapshot = snapshot.start()
        self.addCleanup(snapshot.stop)
        self.server = Server(("127.0.0.1", 0), HeadlessController())
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.addCleanup(self.close)
        self.base = f"http://127.0.0.1:{self.server.server_port}"

    def close(self):
        self.server.updates.stop()
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()

    def http(self, path="/api/system/clock/status", body=None, token="owner"):
        req = urllib.request.Request(self.base + path, data=json.dumps(body).encode() if body is not None else None,
                                     headers={"Authorization": "Bearer " + token, "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=3) as response:
                return response.status, json.load(response)
        except urllib.error.HTTPError as exc:
            return exc.code, json.load(exc)

    def test_management_token_required_for_status_sync_and_logs(self):
        for path, body in [("/api/system/clock/status", None), ("/api/system/clock/sync", {}),
                           ("/api/system/diagnostics", None)]:
            self.assertEqual(self.http(path, body, "mobile-other")[0], 401)
        code, value = self.http()
        self.assertEqual(code, 200)
        self.assertTrue(value["supported"])
        self.assertLess(abs(value["utc_unix"] - time.time()), 2)

    def test_completed_status_reads_time_after_helper_result(self):
        current = [OLD]
        def completed():
            current[0] = NOW
            return [{"phase": "succeeded", "request_id": self.value["request_id"]}]
        with patch.object(system, "_results", side_effect=completed), \
                patch.object(system.time, "time", side_effect=lambda: current[0]):
            value = system.clock_status()
        self.assertEqual(value["phase"], "succeeded")
        self.assertEqual(value["utc_unix"], NOW)

    def test_sync_uses_only_fixed_unit_and_is_idempotent_before_and_after_helper(self):
        body = {"utc_unix": int(time.time()), "request_id": str(uuid.uuid4())}
        with patch.object(system.subprocess, "run") as run:
            self.assertEqual(self.http("/api/system/clock/sync", body)[1]["phase"], "pending")
            self.assertEqual(self.http("/api/system/clock/sync", body)[1]["phase"], "pending")
        run.assert_called_once()
        self.assertEqual(run.call_args.args[0], ["/usr/bin/systemctl", "--no-block", "start", "zeuz-clock-sync.service"])
        requested = json.loads(self.request.read_text())
        result = self.execute(current=time.time, monotonic=time.monotonic, boot_id=BOOT)
        self.assertEqual(result["phase"], "succeeded")
        with patch.object(system.subprocess, "run") as run:
            self.assertEqual(self.http("/api/system/clock/sync", body)[1]["phase"], "succeeded")
        run.assert_not_called()
        self.assertEqual(requested["boot_id"], BOOT)
        self.assertEqual(self.http("/api/system/clock/sync", {**body, "utc_unix": body["utc_unix"] + 1})[0], 400)

    def test_bad_inputs_busy_and_oversize_requests_never_invoke_helper(self):
        body = {"utc_unix": int(time.time()), "request_id": str(uuid.uuid4())}
        with patch.object(system.subprocess, "run") as run:
            for value in [{}, {**body, "utc_unix": True}, {**body, "utc_unix": 0},
                          {**body, "request_id": "invalid"}, {**body, "command": "date"},
                          {**body, "padding": "x" * 2048}]:
                self.assertEqual(self.http("/api/system/clock/sync", value)[0], 400)
            with operation_guard.OperationLease():
                self.assertEqual(self.http("/api/system/clock/sync", body)[0], 409)
        run.assert_not_called()
        self.assertFalse(self.request.exists())

    def test_failed_or_expired_helper_is_not_reported_as_success(self):
        body = {"utc_unix": int(time.time()), "request_id": str(uuid.uuid4())}
        with patch.object(system.subprocess, "run", side_effect=OSError("offline")):
            self.assertEqual(self.http("/api/system/clock/sync", body)[0], 400)
        self.assertFalse(self.request.exists())
        self.request.write_text(json.dumps({**body, "boot_id": BOOT, "monotonic": time.monotonic() - 61}))
        self.assertEqual(self.http()[1]["phase"], "failed")

    def test_diagnostics_are_bounded_without_reading_other_files(self):
        self.log.write_text("".join(f"serial-event-{i:04d} " + "x" * 100 + "\n" for i in range(1000)))
        self.log.with_name(self.log.name + ".1").write_text("old\n" * 1000)
        value = self.http("/api/system/diagnostics")[1]
        self.assertLessEqual(len(value["log_lines"]), 200)
        self.assertLessEqual(len("\n".join(value["log_lines"]).encode()), 32768)
        self.assertIn("serial-event-0999", value["log_lines"][-1])
        self.assertNotIn("owner", json.dumps(value))
        self.log.unlink()
        self.log.symlink_to(self.root / "runtime.json")
        self.assertEqual(self.http("/api/system/diagnostics")[0], 400)

    def test_authenticated_diagnostics_include_passive_serial_observation(self):
        expected = {"phase": "write", "port_open": True, "bytes_queued": 512,
                    "observation": {"available": True, "out_queue": {"available": True, "bytes": 256}}}
        self.serial_snapshot.return_value = expected
        self.assertEqual(self.http("/api/system/diagnostics", token="other")[0], 401)
        self.serial_snapshot.assert_not_called()
        code, value = self.http("/api/system/diagnostics")
        self.assertEqual(code, 200)
        self.assertEqual(value["serial"], expected)
        self.serial_snapshot.assert_called_once_with()


class UpdateClockErrorTests(unittest.TestCase):
    def test_tls_clock_error_is_actionable_without_disabling_verification(self):
        message = updater.update_error(ValueError("[SSL: CERTIFICATE_VERIFY_FAILED] certificate is not yet valid"))
        self.assertIn("reloj", message)
        self.assertIn("Agent", message)

    def test_successful_recheck_clears_old_check_failure_but_keeps_install_failure(self):
        manager = remote_updates.UpdateManager()
        value = {"phase": "available", "latest_revision": "a" * 40, "error": ""}
        previous = {"phase": "failed", "latest_revision": "a" * 40, "error": "old TLS", "failure_stage": "checking"}
        with patch.object(updater, "check_for_update", return_value=dict(value)), patch.object(updater, "_write_state") as write:
            manager._check(previous)
        write.assert_not_called()
        previous.update(request_id=str(uuid.uuid4()), failure_stage="waiting_idle", error="install failure")
        with patch.object(updater, "check_for_update", return_value=dict(value)), patch.object(updater, "_write_state") as write:
            manager._check(previous)
        self.assertEqual(write.call_args.args[1]["error"], "install failure")


if __name__ == "__main__":
    unittest.main()
