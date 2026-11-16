"""Read-only serial observations use mocked descriptors, never a real UART."""
import errno
import importlib.util
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch

from zeuz_core import serial_diagnostics as diagnostics


class ReadOpenPortTests(unittest.TestCase):
    def setUp(self):
        self.port = Mock()
        self.port.fileno.return_value = 43
        self.commands = []
        self.counter_values = list(range(100, 111))
        self.cc = [b"\x00"] * 32
        self.cc[diagnostics.termios.VSTART] = b"\x11"
        self.cc[diagnostics.termios.VSTOP] = b"\x13"
        self.attributes = [diagnostics.termios.IXON | diagnostics.termios.IXOFF,
                           0, diagnostics.termios.CS7 | diagnostics.termios.PARENB,
                           0, diagnostics.termios.B38400, diagnostics.termios.B38400, self.cc]
        replacements = [
            patch.object(diagnostics, "IS_LINUX", True),
            patch.object(diagnostics.os, "fstat", return_value=types.SimpleNamespace(
                st_mode=stat.S_IFCHR | 0o660, st_rdev=diagnostics.os.makedev(188, 7))),
            patch.object(diagnostics.os, "readlink", return_value="../../../../bus/usb-serial/drivers/ftdi_sio"),
            patch.object(diagnostics.termios, "tcgetattr", return_value=self.attributes),
            patch.object(diagnostics.fcntl, "ioctl", side_effect=self.ioctl),
        ]
        for replacement in replacements:
            replacement.start()
            self.addCleanup(replacement.stop)
        # These operations would change serial behavior or consume input.
        for name in ("open", "dup", "read", "write", "close"):
            guard = patch.object(diagnostics.os, name, side_effect=AssertionError("Forbidden " + name))
            forbidden = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(forbidden.assert_not_called)
        for name in ("tcsetattr", "tcflow", "tcflush", "tcdrain", "tcsendbreak"):
            guard = patch.object(diagnostics.termios, name, side_effect=AssertionError("Forbidden " + name))
            forbidden = guard.start()
            self.addCleanup(guard.stop)
            self.addCleanup(forbidden.assert_not_called)

    def ioctl(self, fd, command, values, mutate):
        self.assertEqual(fd, 43)
        self.assertTrue(mutate)
        self.assertEqual(values.itemsize, 4)
        self.commands.append(command)
        if command == diagnostics.TIOCGICOUNT:
            self.assertEqual(len(values), 20)
            for index, value in enumerate(self.counter_values):
                values[index] = value
        elif command == diagnostics.TIOCOUTQ:
            values[0] = 256
        elif command == diagnostics.TIOCINQ:
            values[0] = 3
        elif command == diagnostics.TIOCSERGETLSR:
            values[0] = 1
        else:
            self.fail("Unexpected ioctl, including USB modem-control queries")
        return 0

    def test_verified_ftdi_reads_only_allowed_queries_and_decodes_kernel_settings(self):
        value = diagnostics.read_open_port(self.port)
        self.assertTrue(value["available"])
        self.assertEqual(value["driver"], "ftdi_sio")
        actual = value["termios"]
        self.assertEqual((actual["data_bits"], actual["parity"], actual["stop_bits"]), (7, "E", 1))
        self.assertTrue(actual["ixon"])
        self.assertTrue(actual["ixoff"])
        self.assertFalse(actual["crtscts"])
        self.assertEqual((actual["vstart"], actual["vstop"]), (0x11, 0x13))
        self.assertEqual(value["out_queue"]["bytes"], 256)
        self.assertEqual(value["in_queue"]["bytes"], 3)
        self.assertEqual(value["counters"]["rx"], 104)
        self.assertEqual(value["counters"]["tx"], 105)
        self.assertEqual(value["counters"]["parity"], 108)
        self.assertEqual(value["transmitter_empty"], {"available": True, "empty": True, "source": "driver_cached"})
        self.assertCountEqual(self.commands, [diagnostics.TIOCOUTQ, diagnostics.TIOCINQ,
                                             diagnostics.TIOCGICOUNT, diagnostics.TIOCSERGETLSR])
        diagnostics.os.readlink.assert_called_once_with("/sys/dev/char/188:7/device/driver")
        self.assertLess(len(json.dumps(value)), 1800)

    def test_unverified_driver_never_issues_driver_dependent_queries(self):
        diagnostics.os.readlink.return_value = "../../cp210x"
        value = diagnostics.read_open_port(self.port)
        self.assertTrue(value["termios"]["available"])
        self.assertTrue(value["in_queue"]["available"])
        self.assertEqual(self.commands, [diagnostics.TIOCINQ])
        for field in ("out_queue", "counters", "transmitter_empty"):
            self.assertEqual(value[field], {"available": False, "reason": "driver_not_verified"})

    def test_sysfs_failure_does_not_guess_driver_or_reopen_device(self):
        diagnostics.os.readlink.side_effect = OSError(errno.ENOENT, "absent")
        value = diagnostics.read_open_port(self.port)
        self.assertEqual(value["driver"], "unverified")
        self.assertEqual(self.commands, [diagnostics.TIOCINQ])

    def test_non_character_descriptor_is_not_treated_as_ftdi(self):
        diagnostics.os.fstat.return_value.st_mode = stat.S_IFREG | 0o600
        value = diagnostics.read_open_port(self.port)
        self.assertEqual(value["driver"], "unverified")
        diagnostics.os.readlink.assert_not_called()
        self.assertEqual(self.commands, [diagnostics.TIOCINQ])

    def test_query_failure_is_bounded_and_does_not_hide_other_fields(self):
        def failing_counter(fd, command, values, mutate):
            if command == diagnostics.TIOCGICOUNT:
                raise OSError(errno.ENOTTY, "private-payload-" * 10000)
            return self.ioctl(fd, command, values, mutate)
        diagnostics.fcntl.ioctl.side_effect = failing_counter
        value = diagnostics.read_open_port(self.port)
        self.assertEqual(value["counters"], {"available": False, "reason": "query_unavailable", "errno": errno.ENOTTY})
        self.assertTrue(value["out_queue"]["available"])
        self.assertTrue(value["transmitter_empty"]["available"])
        self.assertNotIn("private-payload", json.dumps(value))
        self.assertLess(len(json.dumps(value)), 1800)

    def test_unavailable_descriptor_and_other_platform_do_not_query(self):
        self.port.fileno.side_effect = OSError(errno.EBADF, "private-data-" * 10000)
        value = diagnostics.read_open_port(self.port)
        self.assertEqual(value["reason"], "descriptor_unavailable")
        self.assertEqual(value["errno"], errno.EBADF)
        self.assertFalse(self.commands)
        diagnostics.termios.tcgetattr.assert_not_called()
        self.port.fileno.reset_mock()
        with patch.object(diagnostics, "IS_LINUX", False):
            value = diagnostics.read_open_port(self.port)
        self.assertEqual(value["reason"], "unsupported_platform")
        self.port.fileno.assert_not_called()

    def test_zero_cached_temt_is_not_reported_as_empty(self):
        def not_empty(fd, command, values, mutate):
            result = self.ioctl(fd, command, values, mutate)
            if command == diagnostics.TIOCSERGETLSR:
                values[0] = 0
            return result
        diagnostics.fcntl.ioctl.side_effect = not_empty
        value = diagnostics.read_open_port(self.port)
        self.assertFalse(value["transmitter_empty"]["empty"])
        self.assertEqual(value["transmitter_empty"]["source"], "driver_cached")


class DescriptorLifetimeTests(unittest.TestCase):
    def setUp(self):
        path = Path(__file__).parents[1] / "serial_transfer.py"
        spec = importlib.util.spec_from_file_location("serial_diagnostic_transfer_test", path)
        self.transfer = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.transfer)
        self.transfer._logger = Mock()
        self.transfer.state = Mock()
        self.threads = []
        self.releases = []
        self.thread_errors = []
        self.addCleanup(self.finish_threads)

    def finish_threads(self):
        for event in self.releases:
            event.set()
        for thread in self.threads:
            thread.join(2)
            self.assertFalse(thread.is_alive(), "A simulated diagnostic/cancel/close deadlocked")
        self.assertEqual(self.thread_errors, [])

    def run_thread(self, function):
        def guarded():
            try:
                function()
            except BaseException as error:
                self.thread_errors.append(error)
        thread = threading.Thread(target=guarded, daemon=True)
        self.threads.append(thread)
        thread.start()
        return thread

    def test_reader_finishes_before_retirement_and_no_query_uses_closed_descriptor(self):
        transfer = self.transfer
        port = Mock()
        transfer._begin_observation("same-fd-test", 10.0)
        transfer._current_ser = port
        entered, release, retiring, closed = (threading.Event() for _ in range(4))
        self.releases.append(release)
        queried = []
        def query(actual):
            self.assertIs(actual, port)
            self.assertFalse(closed.is_set(), "Descriptor was queried after simulated reuse")
            queried.append(actual)
            if len(queried) == 1:
                entered.set()
                self.assertTrue(release.wait(2))
            return {"available": True, "out_queue": {"available": True, "bytes": 256}}
        transfer.read_open_port = query
        results = []
        reader = self.run_thread(lambda: results.append(transfer.get_serial_diagnostics()))
        self.assertTrue(entered.wait(2))
        def retire_and_close():
            retiring.set()
            transfer._retire_serial(port, "write", None)
            # The context manager closes only after _retire_serial returns.
            closed.set()
        owner = self.run_thread(retire_and_close)
        self.assertTrue(retiring.wait(2))
        self.assertFalse(closed.wait(0.03))
        release.set()
        reader.join(2)
        owner.join(2)
        self.assertTrue(closed.is_set())
        self.assertTrue(results[0]["port_open"])
        self.assertEqual(len(queried), 2)  # live query, then pre-close query
        after = transfer.get_serial_diagnostics()
        self.assertFalse(after["port_open"])
        self.assertEqual(after["phase"], "closing")
        self.assertEqual(len(queried), 2)

    def test_busy_observer_returns_without_querying_or_waiting_for_owner(self):
        transfer = self.transfer
        transfer._begin_observation("busy-test", 10.0)
        transfer.read_open_port = Mock(side_effect=AssertionError("Must not query without lifetime lock"))
        with transfer._ser_lock:
            result = transfer.get_serial_diagnostics()
        self.assertEqual(result["observation"], {"available": False, "reason": "busy"})
        self.assertIsNone(result["port_open"])
        transfer.read_open_port.assert_not_called()

    def test_timeout_is_observable_before_blocked_close_and_no_new_ioctl_occurs(self):
        transfer = self.transfer
        clock = [10.0]
        transfer.time = types.SimpleNamespace(monotonic=lambda: clock[0], sleep=Mock())
        transfer._prepare_payload = Mock(return_value=b"x" * 768)
        transfer.read_open_port = Mock(return_value={"available": True, "out_queue": {"available": True, "bytes": 256}})
        close_entered, release_close = threading.Event(), threading.Event()
        self.releases.append(release_close)
        writes = []
        test = self
        class Port:
            def __enter__(self): return self
            def __exit__(self, *args):
                test.assertIsNone(transfer._current_ser)
                close_entered.set()
                test.assertTrue(release_close.wait(2))
                clock[0] += 30.0
            def write(self, data):
                writes.append(bytes(data))
                if len(writes) == 3:
                    clock[0] += 120.0
                    raise transfer.serial.SerialTimeoutException("Write timeout")
                return len(data)
        profile = dict(name="test", baudrate=38400, bytesize=7, parity="E", stopbits=1,
                       flow_control="xonxoff", line_terminator="CRLF", dtr=False, rts=False)
        transfer._transfer_lock.acquire()
        with patch.object(transfer.serial, "Serial", return_value=Port()):
            worker = self.run_thread(lambda: transfer._run_transfer("mock-only", profile, "unused", "redacted"))
            self.assertTrue(close_entered.wait(2))
            queries = transfer.read_open_port.call_count
            pending = transfer.get_serial_diagnostics()
            self.assertFalse(pending["port_open"])
            self.assertEqual(pending["phase"], "closing")
            self.assertEqual(pending["failure_phase"], "write")
            self.assertEqual(pending["error_type"], "SerialTimeoutException")
            self.assertEqual(pending["bytes_queued"], 512)
            self.assertEqual(pending["error_detected_monotonic"], 130.0)
            self.assertIsNone(pending["close_completed_monotonic"])
            self.assertEqual(transfer.read_open_port.call_count, queries)
            self.assertTrue(transfer._logger.error.called, "Timeout must be persisted before close returns")
            release_close.set()
            worker.join(2)
        finished = transfer.get_serial_diagnostics()
        self.assertEqual(finished["phase"], "finished")
        self.assertEqual(finished["outcome"], "error")
        self.assertEqual(finished["close_completed_monotonic"] - finished["close_started_monotonic"], 30.0)
        self.assertEqual(transfer.read_open_port.call_count, queries)
        clock[0] += 200.0
        self.assertEqual(transfer.get_serial_diagnostics()["elapsed_seconds"], finished["elapsed_seconds"])

    def test_payload_configuration_partial_write_and_cancel_match_preserved_072(self):
        baseline_root = os.environ.get("ZEUZ_BASELINE_SOURCE")
        if not baseline_root:
            self.skipTest("Set ZEUZ_BASELINE_SOURCE to the preserved 0.7.2 source directory")
        baseline_path = Path(baseline_root) / "serial_transfer.py"
        self.assertTrue(baseline_path.is_file(), "Configured baseline source is unavailable")
        current_path = Path(__file__).parents[1] / "serial_transfer.py"
        profile = dict(name="test", baudrate=38400, bytesize=7, parity="E", stopbits=1,
                       flow_control="xonxoff", line_terminator="CRLF", dtr=False, rts=False, dripfeed=False)
        def exercise(path, source, cancel):
            spec = importlib.util.spec_from_file_location("serial_preservation_test", path)
            module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(module)
            module._logger = Mock()
            module.state = Mock()
            module.read_open_port = Mock(return_value={"available": False, "reason": "simulated"})
            operations, accepted = [], []
            moment = [100.0]
            def monotonic():
                moment[0] += 0.01
                return moment[0]
            module.time = types.SimpleNamespace(monotonic=monotonic,
                                                sleep=lambda value: operations.append(("sleep", value)))
            class Port:
                def __init__(self, **settings):
                    operations.append(("construct", settings))
                    self.pending = iter((512, 256, 0))
                    self.write_count = 0
                def __setattr__(self, name, value):
                    if name in ("dtr", "rts"):
                        operations.append(("set", name, value))
                    object.__setattr__(self, name, value)
                def __enter__(self):
                    operations.append(("enter",))
                    return self
                def __exit__(self, *args):
                    operations.append(("close",))
                @property
                def out_waiting(self):
                    value = next(self.pending)
                    operations.append(("out_waiting", value))
                    return value
                def cancel_write(self):
                    operations.append(("cancel_write",))
                def write(self, data):
                    self.write_count += 1
                    amount = 7 if self.write_count == 1 else len(data)
                    operations.append(("write", bytes(data), amount))
                    accepted.append(bytes(data[:amount]))
                    if cancel:
                        module.request_cancel()
                    return amount
            module._transfer_lock.acquire()
            with patch.object(module.serial, "Serial", Port):
                module._run_transfer("SIMULATED-NO-DEVICE", dict(profile), str(source), "synthetic.nc")
            return operations, b"".join(accepted), module.state.update_transfer.call_args_list
        with tempfile.TemporaryDirectory() as directory:
            source = Path(directory) / "synthetic.nc"
            source.write_bytes(b"%\r\nO0002\n" + b"N10 G01 X1.0\r" * 80 + b"M30\r\n%\n")
            for cancel in (False, True):
                with self.subTest(cancel=cancel):
                    before = exercise(baseline_path, source, cancel)
                    after = exercise(current_path, source, cancel)
                    self.assertEqual(after, before)
                    self.assertEqual(after[0][0][1]["write_timeout"], 120)
                    self.assertTrue(after[0][0][1]["xonxoff"])
                    self.assertIn(("set", "dtr", False), after[0])
                    self.assertIn(("set", "rts", False), after[0])
                    if cancel:
                        self.assertEqual(len(after[1]), 7)
                        self.assertIn(("cancel_write",), after[0])
                    else:
                        self.assertEqual([operation for operation in after[0] if operation[0] == "sleep"],
                                         [("sleep", 0.05), ("sleep", 0.05), ("sleep", 0.3)])


if __name__ == "__main__":
    unittest.main()
