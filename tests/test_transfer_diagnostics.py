"""Transfer outcomes remain inspectable without unbounded storage growth."""
import io
import logging
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from zeuz_core import transfer_diagnostics as diagnostics


class TransferDiagnosticsTests(unittest.TestCase):
    def setUp(self):
        self.logger = logging.Logger("test.zeuz.serial")
        self.stderr = io.StringIO()
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "logs" / "transfer-errors.log"
        self.get_logger = patch.object(diagnostics.logging, "getLogger", return_value=self.logger)
        self.get_logger.start()
        self.addCleanup(self.get_logger.stop)
        stderr_patch = patch.object(diagnostics.sys, "stderr", self.stderr)
        stderr_patch.start()
        self.addCleanup(stderr_patch.stop)
        self.addCleanup(self.close_handlers)

    def close_handlers(self):
        for handler in self.logger.handlers[:]:
            self.logger.removeHandler(handler)
            handler.close()

    def test_repeated_configuration_records_error_once_in_file_and_stderr(self):
        self.assertTrue(diagnostics.configure_transfer_diagnostics(self.path))
        self.assertTrue(diagnostics.configure_transfer_diagnostics(self.path))
        self.assertEqual(len(self.logger.handlers), 2)
        self.logger.error("phase=write error=SerialTimeoutException")
        self.assertEqual(self.path.read_text().count("phase=write"), 1)
        self.assertEqual(self.stderr.getvalue().count("phase=write"), 1)
        persistent = next(h for h in self.logger.handlers if getattr(h, "_zeuz_transfer_handler") == "file")
        self.assertEqual(persistent.maxBytes, 128 * 1024)
        self.assertEqual(persistent.backupCount, 2)

    def test_rotation_retains_only_two_backups(self):
        with patch.object(diagnostics, "MAX_LOG_BYTES", 256):
            self.assertTrue(diagnostics.configure_transfer_diagnostics(self.path))
        for number in range(30):
            self.logger.error("failure=%03d phase=write queued_bytes=256 total_bytes=8192", number)
        files = sorted(self.path.parent.iterdir())
        self.assertEqual([p.name for p in files], ["transfer-errors.log", "transfer-errors.log.1", "transfer-errors.log.2"])
        self.assertTrue(all(p.stat().st_size <= 256 for p in files))
        self.assertIn("failure=029", self.path.read_text())
        self.assertNotIn("failure=000", "".join(p.read_text() for p in files))

    def test_info_success_and_cancel_are_persisted_once(self):
        self.assertTrue(diagnostics.configure_transfer_diagnostics(self.path))
        self.assertTrue(diagnostics.configure_transfer_diagnostics(self.path))
        self.logger.info("outcome=success bytes_queued=100 cnc_receipt_confirmed=false")
        self.logger.info("outcome=cancelled bytes_queued=0 cnc_receipt_confirmed=false")
        for outcome in ("success", "cancelled"):
            self.assertEqual(self.path.read_text().count("outcome=" + outcome), 1)
            self.assertEqual(self.stderr.getvalue().count("outcome=" + outcome), 1)

    def test_unwritable_directory_keeps_stderr_and_can_recover(self):
        with patch.object(diagnostics.Path, "mkdir", side_effect=PermissionError("read-only storage")):
            self.assertFalse(diagnostics.configure_transfer_diagnostics(self.path))
        self.logger.error("serial failure after storage error")
        self.assertIn("serial failure after storage error", self.stderr.getvalue())
        self.assertEqual(len(self.logger.handlers), 1)
        self.assertTrue(diagnostics.configure_transfer_diagnostics(self.path))
        self.logger.error("serial failure after storage recovery")
        self.assertIn("serial failure after storage recovery", self.path.read_text())


if __name__ == "__main__":
    unittest.main()
