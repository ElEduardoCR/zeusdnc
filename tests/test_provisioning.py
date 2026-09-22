import json
import tempfile
import time
import unittest
from pathlib import Path
from subprocess import CompletedProcess

from zeuz_provisioning.controller import ProvisioningController


class ProvisioningControllerTests(unittest.TestCase):
    @staticmethod
    def machine_saver(machine):
        return {**machine, "id": "torno-1"}, None

    def test_rejects_invalid_or_oversized_credentials(self) -> None:
        controller = ProvisioningController(state_path=Path("/unused"))
        ok, _ = controller.handle_command(b"not-json")
        self.assertFalse(ok)
        ok, _ = controller.handle_command(
            json.dumps({"action": "configure_wifi", "ssid": "x" * 33}).encode()
        )
        self.assertFalse(ok)

    def test_connects_without_exposing_password_in_persisted_state(self) -> None:
        calls = []

        def runner(command, **kwargs):
            calls.append(command)
            return CompletedProcess(command, 0, "conectado", "")

        with tempfile.TemporaryDirectory() as directory:
            state_path = Path(directory) / "network.json"
            controller = ProvisioningController(
                state_path=state_path,
                runner=runner,
                machine_saver=self.machine_saver,
            )
            machine_command = {
                "action": "machine",
                "m": {
                    "n": "Torno 1", "b": 9600, "d": 8, "p": "N", "s": 1,
                    "f": "xonxoff", "l": "CRLF", "t": False, "r": False,
                    "g": False,
                },
            }
            self.assertLessEqual(len(json.dumps(machine_command, separators=(",", ":")).encode()), 185)
            ok, _ = controller.handle_command(
                json.dumps(machine_command, separators=(",", ":")).encode()
            )
            self.assertTrue(ok)
            ok, _ = controller.handle_command(
                json.dumps({"action": "wifi", "s": "Taller", "p": "secreto-123"}).encode()
            )
            self.assertTrue(ok)
            deadline = time.monotonic() + 2
            while controller.snapshot()["state"] == "connecting" and time.monotonic() < deadline:
                time.sleep(0.01)
            self.assertEqual(controller.snapshot()["state"], "connected")
            self.assertEqual(calls[0], ["nmcli", "radio", "wifi", "on"])
            self.assertEqual(calls[1][:7], ["nmcli", "--wait", "45", "device", "wifi", "connect", "Taller"])
            persisted = state_path.read_text(encoding="utf-8")
            self.assertIn("Taller", persisted)
            self.assertIn("torno-1", persisted)
            self.assertNotIn("secreto-123", persisted)

    def test_rejects_invalid_machine(self) -> None:
        controller = ProvisioningController(
            state_path=Path("/unused"),
            machine_saver=lambda machine: (None, "El nombre es obligatorio"),
        )
        ok, message = controller.handle_command(
            json.dumps({"action": "machine", "m": {"n": ""}}).encode()
        )
        self.assertFalse(ok)
        self.assertIn("nombre", message)

    def test_reports_nmcli_failure(self) -> None:
        def runner(command, **kwargs):
            return CompletedProcess(command, 10, "", "Credenciales incorrectas")

        controller = ProvisioningController(state_path=Path("/unused"), runner=runner)
        ok, _ = controller.handle_command(
            json.dumps(
                {"action": "configure_wifi", "ssid": "Taller", "password": "incorrecta"}
            ).encode()
        )
        self.assertTrue(ok)
        deadline = time.monotonic() + 2
        while controller.snapshot()["state"] == "connecting" and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(controller.snapshot()["state"], "error")
        self.assertIn("Credenciales", controller.snapshot()["error"])


if __name__ == "__main__":
    unittest.main()
