from __future__ import annotations

import subprocess
import unittest

from zeuz_core.network import WifiManager, _split_nmcli


class FakeRunner:
    def __init__(self, outputs: list[tuple[int, str, str]]) -> None:
        self.outputs = list(outputs)
        self.calls: list[list[str]] = []

    def __call__(self, command, **_kwargs):
        self.calls.append(command)
        returncode, stdout, stderr = self.outputs.pop(0)
        return subprocess.CompletedProcess(command, returncode, stdout, stderr)


class WifiManagerTests(unittest.TestCase):
    def test_split_nmcli_honors_escaped_colons(self) -> None:
        self.assertEqual(
            _split_nmcli(r"*:Planta\: CNC:87:WPA2"),
            ["*", "Planta: CNC", "87", "WPA2"],
        )

    def test_scan_deduplicates_and_sorts_networks(self) -> None:
        runner = FakeRunner(
            [
                (0, "", ""),
                (
                    0,
                    "*:Taller:74:WPA2\n:Taller:35:WPA2\n:Invitados:92:\n",
                    "",
                ),
            ]
        )
        networks = WifiManager(runner=runner, command_prefix=[]).scan()
        self.assertEqual([item["ssid"] for item in networks], ["Taller", "Invitados"])
        self.assertTrue(networks[0]["active"])
        self.assertEqual(networks[1]["security"], "Abierta")

    def test_status_reports_ip_without_cidr(self) -> None:
        runner = FakeRunner(
            [
                (0, "wlan0:wifi:connected:Planta\\: CNC\n", ""),
                (0, "192.168.20.18/24\n", ""),
            ]
        )
        status = WifiManager(runner=runner, command_prefix=[]).status()
        self.assertEqual(status["ssid"], "Planta: CNC")
        self.assertEqual(status["ip"], "192.168.20.18")

    def test_connect_never_places_password_in_an_error(self) -> None:
        runner = FakeRunner([(0, "", ""), (10, "", "No se pudo autenticar")])
        manager = WifiManager(runner=runner, command_prefix=[])
        with self.assertRaisesRegex(RuntimeError, "No se pudo autenticar"):
            manager.connect("Taller", "secreto-industrial")
        self.assertNotIn("secreto-industrial", str(runner.outputs))


if __name__ == "__main__":
    unittest.main()
