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


if __name__ == "__main__":
    unittest.main()
