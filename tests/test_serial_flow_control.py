"""A paused or disconnected CNC must not produce a completed transfer."""
from __future__ import annotations

import hashlib
import importlib.util
from pathlib import Path
import unittest
from unittest.mock import patch

from state import AppState


ROOT = Path(__file__).resolve().parents[1]
PROFILE = {"id": "test", "name": "Test", "baudrate": 4800, "bytesize": 8,
           "parity": "N", "stopbits": 1, "flow_control": "xonxoff",
           "line_terminator": "LF"}


class Clock:
    def __init__(self):
        self.now = 0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        # A polling step stands for a long receiver pause without slowing the
        # test suite. The adapter FIFO margin is not part of the drain deadline.
        self.now += 50 if seconds == .05 else seconds


class Port:
    def __init__(self, pending=(0,), *, write_limit=None, write_error=None):
        self.pending = iter(pending)
        self.last_pending = 0
        self.write_limit = write_limit
        self.write_error = write_error
        self.received = bytearray()
        self.closed = False
        self.write_calls = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.closed = True

    def write(self, data):
        self.write_calls += 1
        if self.write_error:
            raise self.write_error
        count = len(data) if self.write_limit is None else min(self.write_limit, len(data))
        self.received.extend(data[:count])
        return count

    @property
    def out_waiting(self):
        self.last_pending = next(self.pending, self.last_pending)
        if isinstance(self.last_pending, Exception):
            raise self.last_pending
        return self.last_pending


class SerialFlowControlTests(unittest.TestCase):
    def setUp(self):
        # Legacy tests sometimes mock serial_transfer in sys.modules.
        spec = importlib.util.spec_from_file_location("flow_sender_under_test", ROOT / "serial_transfer.py")
        self.sender = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.sender)
        self.sender.state = AppState()
        self.clock = Clock()

    def run_transfer(self, port, *, dripfeed=False, raw=b"O100\nG1 X1\nM30\n", sleep=None):
        self.sender._transfer_lock.acquire()
        with patch.object(self.sender, "_prepare_payload", return_value=raw), \
             patch.object(self.sender.serial, "Serial", return_value=port) as factory, \
             patch.object(self.sender.time, "monotonic", side_effect=self.clock.monotonic), \
             patch.object(self.sender.time, "sleep", side_effect=sleep or self.clock.sleep):
            self.sender._run_transfer("TEST_ONLY", {**PROFILE, "dripfeed": dripfeed},
                                      None, "test.nc")
        self.serial_options = factory.call_args.kwargs
        self.assertTrue(port.closed)
        self.assertFalse(self.sender._transfer_lock.locked())
        return self.sender.state.snapshot()["transfer"]

    def test_receiver_can_resume_after_pause_and_finish(self):
        port = Port((100, 100, 100, 50, 50, 50, 10, 0))
        result = self.run_transfer(port)
        self.assertGreater(self.clock.now, 120)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(port.received, b"O100\nG1 X1\nM30\n")

    def test_punch_allows_two_minutes_of_flow_pause_and_dripfeed_is_unlimited(self):
        for dripfeed, expected_timeout in ((False, 120), (True, None)):
            with self.subTest(dripfeed=dripfeed):
                result = self.run_transfer(Port(), dripfeed=dripfeed)
                self.assertEqual(result["status"], "success", result)
                self.assertEqual(self.serial_options["write_timeout"], expected_timeout)
                self.assertTrue(self.serial_options["xonxoff"])

    def test_receiver_stuck_in_flow_pause_is_error_not_success(self):
        with self.assertLogs("zeuz.serial", level="ERROR"):
            result = self.run_transfer(Port((100,)))
        self.assertEqual(result["status"], "error", result)
        self.assertIn("Se agoto el tiempo", result["message"])

    def test_disconnected_adapter_during_drain_is_error_not_success(self):
        with self.assertLogs("zeuz.serial", level="ERROR"):
            result = self.run_transfer(Port((10, OSError("adapter disconnected"))))
        self.assertEqual(result["status"], "error", result)
        self.assertIn("adapter disconnected", result["message"])

    def test_partial_write_keeps_all_program_bytes_in_order(self):
        port = Port(write_limit=3)
        raw = b"O100\n" + b"G1 X1\n" * 100 + b"M30\n"
        result = self.run_transfer(port, raw=raw)
        self.assertEqual(result["status"], "success", result)
        self.assertEqual(bytes(port.received), raw)
        self.assertEqual(result["bytes_sent"], len(raw))

    def test_zero_write_does_not_claim_program_was_sent(self):
        with self.assertLogs("zeuz.serial", level="ERROR"):
            result = self.run_transfer(Port(write_limit=0))
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result["bytes_sent"], 0)

    def test_write_timeout_reports_error_without_resending_uncertain_bytes(self):
        port = Port(write_error=self.sender.serial.SerialTimeoutException("Write timeout"))
        with self.assertLogs("zeuz.serial", level="ERROR") as log:
            result = self.run_transfer(port, raw=b"(PRIVATE CNC PROGRAM)\nM30\n")
        self.assertEqual(result["status"], "error", result)
        self.assertEqual(result["bytes_sent"], 0)
        self.assertEqual(port.received, b"")
        self.assertEqual(port.write_calls, 1, "A timed-out write has an uncertain byte count and must not be retried")
        self.assertIn("120 s", result["message"])
        self.assertIn("control de flujo", result["message"])
        detail = "\n".join(log.output)
        self.assertIn("phase=write", detail)
        self.assertIn("port='TEST_ONLY'", detail)
        self.assertIn("bytes_queued=0", detail)
        self.assertIn("'flow_control': 'xonxoff'", detail)
        self.assertIn("SerialTimeoutException: Write timeout", detail)
        self.assertNotIn("PRIVATE CNC PROGRAM", detail)

    def test_success_logs_boundaries_and_prepared_hash_without_program_contents(self):
        raw = b"(PRIVATE CNC PROGRAM)\n" + b"G1 X1\n" * 100 + b"M30\n"
        port = Port()
        with self.assertLogs("zeuz.serial", level="INFO") as log, \
                patch.object(self.sender.time, "time", side_effect=[1, 500_000_000, 1_000_000_000]):
            result = self.run_transfer(port, raw=raw)
        self.assertEqual(result["status"], "success")
        self.assertEqual(port.received, raw)
        self.assertEqual(len(log.records), 3, "Only start, pre-close observation and terminal outcome are logged")
        started, closing, finished = (record.getMessage() for record in log.records)
        self.assertIn("serial_transfer started", started)
        self.assertIn('"phase":"closing"', closing)
        self.assertIn("outcome=success", finished)
        self.assertIn("bytes_queued=" + str(len(raw)), finished)
        self.assertIn("prepared_sha256=" + hashlib.sha256(raw).hexdigest(), finished)
        self.assertIn("elapsed_seconds=0.300", finished)
        self.assertIn("cnc_receipt_confirmed=false", finished)
        start_id = started.split("transfer_id=", 1)[1].split()[0]
        self.assertIn("transfer_id=" + start_id, finished)
        self.assertNotIn("PRIVATE CNC PROGRAM", "\n".join(log.output))

    def test_cancel_before_first_write_records_zero_bytes_and_terminal_outcome(self):
        self.sender._cancel_event.set()
        port = Port()
        with self.assertLogs("zeuz.serial", level="INFO") as log:
            result = self.run_transfer(port)
        self.assertEqual(result["status"], "cancelled")
        self.assertEqual(port.write_calls, 0)
        self.assertEqual(len(log.records), 3)
        detail = log.records[-1].getMessage()
        self.assertIn("outcome=cancelled", detail)
        self.assertIn("bytes_queued=0", detail)
        self.assertIn("cnc_receipt_confirmed=false", detail)

    def test_source_failure_records_terminal_error_before_port_is_opened(self):
        self.sender._transfer_lock.acquire()
        with self.assertLogs("zeuz.serial", level="INFO") as log, \
                patch.object(self.sender, "_prepare_payload", side_effect=FileNotFoundError("missing source")), \
                patch.object(self.sender.serial, "Serial") as factory:
            self.sender._run_transfer("TEST_ONLY", PROFILE, None, "test.nc")
        factory.assert_not_called()
        self.assertFalse(self.sender._transfer_lock.locked())
        self.assertEqual(self.sender.state.snapshot()["transfer"]["status"], "error")
        self.assertEqual(len(log.records), 2)
        detail = log.records[-1].getMessage()
        self.assertIn("outcome=error phase=prepare", detail)
        self.assertIn("bytes_queued=0 total_bytes=0 prepared_sha256=None", detail)

    def test_dripfeed_can_pause_for_minutes_and_cancel(self):
        def pause_and_cancel(seconds):
            self.clock.sleep(seconds)
            if self.clock.now > 300:
                self.sender._cancel_event.set()

        result = self.run_transfer(Port((100,)), dripfeed=True, sleep=pause_and_cancel)
        self.assertGreater(self.clock.now, 300)
        self.assertEqual(result["status"], "cancelled", result)

    def test_cancelled_short_write_does_not_send_remaining_program(self):
        port = Port(write_limit=3)
        original_write = port.write

        def cancelled_write(data):
            written = original_write(data)
            self.sender._cancel_event.set()
            return written

        port.write = cancelled_write
        result = self.run_transfer(port)
        self.assertEqual(result["status"], "cancelled", result)
        self.assertEqual(port.received, b"O10")


if __name__ == "__main__":
    unittest.main()
