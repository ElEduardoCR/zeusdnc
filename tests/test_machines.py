from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import machines


class MachineStorageTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "machines.json"
        self.path_patch = patch.object(machines, "MACHINES_PATH", str(self.path))
        self.path_patch.start()

    def tearDown(self) -> None:
        self.path_patch.stop()
        self.temporary.cleanup()

    @staticmethod
    def profile(name: str = "Torno 1") -> dict:
        return {
            "name": name,
            "baudrate": 9600,
            "bytesize": 7,
            "parity": "E",
            "stopbits": 1,
            "flow_control": "none",
            "line_terminator": "CRLF",
            "dtr": False,
            "rts": True,
            "dripfeed": False,
        }

    def test_create_edit_and_delete_machine(self) -> None:
        created, error = machines.save_machine(self.profile())
        self.assertIsNone(error)
        self.assertEqual(created["id"], "torno-1")

        edited_data = {**created, "name": "Torno principal", "baudrate": 19200}
        edited, error = machines.save_machine(edited_data)
        self.assertIsNone(error)
        self.assertEqual(edited["id"], created["id"])
        self.assertEqual(machines.load_machines()[0]["baudrate"], 19200)

        deleted, error = machines.delete_machine(created["id"])
        self.assertTrue(deleted)
        self.assertIsNone(error)
        self.assertEqual(machines.load_machines(), [])

    def test_duplicate_names_receive_unique_ids_and_valid_json(self) -> None:
        first, _ = machines.save_machine(self.profile())
        second, _ = machines.save_machine(self.profile())
        self.assertEqual(first["id"], "torno-1")
        self.assertEqual(second["id"], "torno-1-2")
        self.assertEqual(len(json.loads(self.path.read_text())["machines"]), 2)

    def test_invalid_profile_does_not_modify_storage(self) -> None:
        created, _ = machines.save_machine(self.profile())
        invalid = {**created, "bytesize": 9}
        result, error = machines.save_machine(invalid)
        self.assertIsNone(result)
        self.assertIn("5, 6, 7 u 8", error)
        self.assertEqual(machines.load_machines(), [created])


if __name__ == "__main__":
    unittest.main()
