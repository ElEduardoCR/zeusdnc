"""Only the send that owns the port may replace the status that clients poll."""
from __future__ import annotations

import importlib.util
from pathlib import Path
import threading
import unittest
from unittest.mock import patch

from state import AppState


ROOT = Path(__file__).resolve().parents[1]
PROFILE = {"id": "fadal", "name": "FADAL", "baudrate": 19200, "bytesize": 7,
           "parity": "E", "stopbits": 1, "flow_control": "xonxoff",
           "line_terminator": "CRLF"}


class Lease:
    def close(self):
        pass


class StartTransferStatusTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("start_sender_under_test", ROOT / "serial_transfer.py")
        self.sender = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sender)
        self.sender.state = AppState()

    def test_reply_already_reports_sending_instead_of_previous_result(self):
        self.sender.state.update_transfer(status="success", filename="2222.nc", percent=100,
                                          message="Transferencia completada")
        release = threading.Event()
        seen = {}

        def worker(device, profile, path, name):
            seen.update(self.sender.state.snapshot()["transfer"])
            release.wait(5)

        with patch.object(self.sender, "OperationLease", return_value=Lease()), \
             patch.object(self.sender, "_run_transfer", side_effect=worker):
            ok, error = self.sender.start_transfer("/dev/ttyUSB0", PROFILE, "/tmp/1001.nc", "1001.nc")
            transfer = self.sender.state.snapshot()["transfer"]
            release.set()
        self.assertEqual((ok, error), (True, None))
        self.assertEqual(transfer["status"], "sending")
        self.assertEqual(transfer["filename"], "1001.nc")
        self.assertEqual(transfer["machine"], "FADAL")
        self.assertEqual((transfer["bytes_sent"], transfer["percent"]), (0, 0))
        self.assertEqual(transfer["message"], "Preparando el envío…")

    def test_rejected_second_send_keeps_running_progress(self):
        running = {"status": "sending", "filename": "1001.nc", "machine": "FADAL",
                   "bytes_sent": 4096, "total_bytes": 91804, "percent": 4, "message": ""}
        self.sender.state.update_transfer(**running)
        self.assertTrue(self.sender._transfer_lock.acquire(blocking=False))
        try:
            ok, error = self.sender.start_transfer("/dev/ttyUSB0", PROFILE, "/tmp/1002.nc", "1002.nc")
        finally:
            self.sender._transfer_lock.release()
        self.assertFalse(ok)
        self.assertIn("transferencia en curso", error)
        self.assertEqual(self.sender.state.snapshot()["transfer"], running)

    def test_port_used_by_touchscreen_keeps_status_and_releases_lock(self):
        self.sender.state.update_transfer(status="success", filename="2222.nc", percent=100)
        before = self.sender.state.snapshot()["transfer"]
        with patch.object(self.sender, "OperationLease", side_effect=self.sender.Busy()):
            ok, _ = self.sender.start_transfer("/dev/ttyUSB0", PROFILE, "/tmp/1003.nc", "1003.nc")
        self.assertFalse(ok)
        self.assertEqual(self.sender.state.snapshot()["transfer"], before)
        self.assertTrue(self.sender._transfer_lock.acquire(blocking=False))
        self.sender._transfer_lock.release()


if __name__ == "__main__":
    unittest.main()
