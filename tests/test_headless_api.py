import tempfile
import unittest
import sys
from pathlib import Path
from unittest.mock import Mock, patch

from state import state

# La Mac de pruebas no necesita pyserial: el arranque real de la transferencia
# se sustituye abajo y la imagen ARM64 sí instala python3-serial.
sys.modules.setdefault("serial_transfer", Mock())
from zeuz_core.headless_api import HeadlessController


class HeadlessControllerTests(unittest.TestCase):
    def setUp(self) -> None:
        state.usb_devices = {}
        state.active_device = None
        state.active_machine_id = None
        state.reset_transfer()

    def test_send_materializes_from_current_repository(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "zeuz-send-test.nc"
            program.write_text("O1\nM30\n", encoding="ascii")
            repository = Mock()
            repository.materialize.return_value = program
            settings = Mock()
            settings.repository.return_value = repository
            state.on_usb_add("/dev/ttyUSB9", "Prueba")
            state.select_machine("fanuc")

            def start_transfer(device, profile, path, name):
                state.update_transfer(status="success")
                return True, None

            controller = HeadlessController()
            with patch("zeuz_core.headless_api.RuntimeSettings.load", return_value=settings), patch(
                "zeuz_core.headless_api.get_machine", return_value={"id": "fanuc", "name": "Fanuc"}
            ), patch("zeuz_core.headless_api.serial_transfer.start_transfer", side_effect=start_transfer):
                controller.send("carpeta/O1.nc")

            repository.materialize.assert_called_once_with("carpeta/O1.nc")
            self.assertEqual(state.snapshot()["transfer"]["status"], "success")

    def test_info_reports_agent_configuration(self) -> None:
        settings = Mock(source_type="agent", agent_token="token")
        with patch("zeuz_core.headless_api.RuntimeSettings.load", return_value=settings):
            info = HeadlessController.info()
        self.assertTrue(info["agent_configured"])
        self.assertEqual(info["service"], "zeuz-dnc")
        self.assertRegex(info["version"], r"^\d+\.\d+\.\d+$")

    def test_agent_supplies_profile_and_pi_selects_adapter_automatically(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            program = Path(directory) / "zeuz-send-agent.nc"
            program.write_text("O2\nM30\n", encoding="ascii")
            repository = Mock()
            repository.materialize.return_value = program
            settings = Mock()
            settings.repository.return_value = repository
            state.on_usb_add("/dev/ttyUSB4", "Adaptador")
            supplied = {
                "id": "mori-1",
                "name": "Torno Mori 1",
                "baudrate": 9600,
                "bytesize": 8,
                "parity": "N",
                "stopbits": 1,
                "flow_control": "xonxoff",
                "line_terminator": "CRLF",
            }

            controller = HeadlessController()
            with patch("zeuz_core.headless_api.RuntimeSettings.load", return_value=settings), patch(
                "zeuz_core.headless_api.serial_transfer.start_transfer", return_value=(True, None)
            ) as transfer:
                controller.send("O2.nc", supplied)

            device, profile, _, _ = transfer.call_args.args
            self.assertEqual(device, "/dev/ttyUSB4")
            self.assertEqual(profile["name"], "Torno Mori 1")
            self.assertEqual(profile["baudrate"], 9600)

    def test_rejected_send_keeps_status_and_file_of_running_transfer(self) -> None:
        from zeuz_core.headless_api import Conflict

        with tempfile.TemporaryDirectory() as directory:
            rejected = Path(directory) / "zeuz-send-segundo.nc"
            rejected.write_text("O3\nM30\n", encoding="ascii")
            running = {"status": "sending", "filename": "1001.nc", "bytes_sent": 4096,
                       "total_bytes": 91804, "percent": 4}

            def materialize(path):
                # Another send won the port while this request read its program.
                state.update_transfer(**running)
                return rejected

            repository = Mock()
            repository.materialize.side_effect = materialize
            settings = Mock()
            settings.repository.return_value = repository
            state.on_usb_add("/dev/ttyUSB4", "Adaptador")
            supplied = {"id": "fadal", "name": "FADAL", "baudrate": 19200, "bytesize": 7, "parity": "E",
                        "stopbits": 1, "flow_control": "xonxoff", "line_terminator": "CRLF"}
            with patch("zeuz_core.headless_api.RuntimeSettings.load", return_value=settings), patch(
                "zeuz_core.headless_api.serial_transfer.start_transfer",
                return_value=(False, "Ya hay una transferencia en curso"),
            ):
                with self.assertRaises(Conflict):
                    HeadlessController().send("O3.nc", supplied)

            transfer = state.snapshot()["transfer"]
            self.assertEqual(transfer["status"], "sending")
            self.assertEqual(transfer["filename"], "1001.nc")
            self.assertEqual(transfer["bytes_sent"], 4096)
            self.assertFalse(rejected.exists(), "The rejected request removes only its own copy")


class DeviceIdentityTests(unittest.TestCase):
    def test_board_serial_is_used_before_clonable_machine_id(self):
        from zeuz_core.headless_api import device_identity
        with patch("zeuz_core.headless_api.Path.read_text", return_value="board-A\x00") as read:
            first = device_identity()
            self.assertEqual(first, device_identity())
            self.assertEqual(read.call_count, 2)
        with patch("zeuz_core.headless_api.Path.read_text", return_value="board-B\x00"):
            self.assertNotEqual(first, device_identity())

    def test_no_identity_is_invented_if_ids_are_unavailable(self):
        from zeuz_core.headless_api import device_identity
        with patch("zeuz_core.headless_api.Path.read_text", side_effect=FileNotFoundError):
            self.assertIsNone(device_identity())


if __name__ == "__main__":
    unittest.main()
