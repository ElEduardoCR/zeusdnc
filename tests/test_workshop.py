"""Real HTTP contracts with simulated CNC; never accesses serial hardware."""
import base64
import hashlib
import json
import os
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

sys.modules.setdefault("serial_transfer", Mock())
import machines
from zeuz_core import workshop
from zeuz_core.headless_api import HeadlessController, Server
from zeuz_core.settings import RuntimeSettings
from zeuzagent.config import AgentConfig
from zeuzagent.library import ProgramLibrary
from zeuzagent.machines import MachineConflict, MachineRegistry, serial_profile
from zeuzagent.server import create_server
from zeuzagent.workshop import WorkshopSync


class Controller(HeadlessController):
    def __init__(self):
        super().__init__()
        self.sent = []

    def send(self, path, supplied_profile=None):
        raw = RuntimeSettings.load().repository().materialize(path).read_bytes()
        self.sent.append((path, raw, supplied_profile))


class WorkshopTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.patches = [
            patch.object(machines, "MACHINES_PATH", str(self.root / "pi-machines.json")),
            patch.object(workshop, "settings_path", return_value=self.root / "workshop.json"),
            patch.dict(os.environ, {"ZEUZ_PROGRAMS_DIR": str(self.root / "pi-programs"), "ZEUZ_PROGRAM_SOURCE": "local"}),
        ]
        for item in self.patches: item.start()
        self.controller = Controller()
        self.pi = Server(("127.0.0.1", 0), self.controller)
        self.thread = threading.Thread(target=self.pi.serve_forever, daemon=True)
        self.thread.start()
        self.url = f"http://127.0.0.1:{self.pi.server_port}"
        self.registry = MachineRegistry(self.root / "agent-machines.json")
        self.config = AgentConfig("Test", str(self.root / "pc-programs"), host="127.0.0.1", port=0, api_token="t" * 32, pairing_code="123456", discovery=False, program_server_host="127.0.0.1", program_server_port=self.pi.server_port)
        Path(self.config.programs_dir).mkdir()
        self.machine = self.registry.save({"id": "lathe", "name": "Torno", "dnc_host": "127.0.0.1", "dnc_port": self.pi.server_port, "baudrate": 9600})
        self.sync = WorkshopSync(self.config, self.registry)

    def tearDown(self):
        self.pi.shutdown()
        self.pi.server_close()
        self.thread.join()
        for item in reversed(self.patches): item.stop()
        self.temp.cleanup()

    def request(self, method, path, body=None, url=None):
        req = urllib.request.Request((url or self.url) + path, data=json.dumps(body).encode() if body is not None else None, method=method, headers={"Content-Type": "application/json", "Authorization": "Bearer " + self.config.api_token})
        with urllib.request.urlopen(req, timeout=3) as response:
            return json.load(response)

    def test_computer_leaves_mobile_reads_edits_sends_then_reconciles(self):
        original = b"%\r\nO1\r\n(caf\xe9)\r\nM30\r\n%"
        (Path(self.config.programs_dir) / "O1.nc").write_bytes(original)
        self.sync.cycle()
        self.assertTrue(self.sync.status.startswith("Sincronizado"), self.sync.status)
        agent = create_server(self.config, ProgramLibrary(Path(self.config.programs_dir)), self.registry)
        thread = threading.Thread(target=agent.serve_forever, daemon=True)
        thread.start()
        agent_url = f"http://127.0.0.1:{agent.server_port}"
        try:
            self.assertEqual(self.request("GET", "/v1/workshop", url=agent_url)["server_url"], self.url)
            self.assertEqual(self.request("GET", "/v1/programs", url=agent_url)["entries"][0]["name"], "O1.nc")
        finally:
            agent.shutdown()
            agent.server_close()
            thread.join()
        self.assertEqual(self.request("GET", "/v1/programs/content?path=O1.nc")["content"].encode("latin-1"), original)
        current = self.request("GET", "/v1/dnc/machines")[0]
        saved = self.request("POST", "/v1/dnc/machine/save", {**current, "baudrate": 19200})["machine"]
        self.request("POST", "/v1/dnc/send", {"path": "O1.nc", "machine_id": "lathe"})
        self.assertEqual(self.controller.sent[-1][1], original)
        self.assertEqual(self.controller.sent[-1][2]["baudrate"], 19200)
        touch, error = machines.save_machine({**saved, "name": "Torno norte", "parity": "E"})
        self.assertIsNone(error)
        self.assertEqual(self.request("GET", "/v1/dnc/machines")[0]["name"], "Torno norte")
        restarted = WorkshopSync(self.config, self.registry)
        restarted.cycle()
        self.assertEqual(serial_profile(self.registry.get("lathe")), serial_profile(touch))
        self.assertEqual(self.registry.get("lathe")["revision"], touch["revision"])
        self.assertTrue(restarted.status.startswith("Sincronizado"), restarted.status)

    def test_mirror_preserves_history_deletions_and_server_edits(self):
        program = Path(self.config.programs_dir) / "O2.nc"
        program.write_bytes(b"old\r\n\xff")
        self.sync.cycle()
        program.write_bytes(b"new\r\n")
        self.sync.cycle()
        root = self.root / "pi-programs"
        self.assertEqual((root / "O2.nc").read_bytes(), b"new\r\n")
        digest = hashlib.sha256(b"old\r\n\xff").hexdigest()
        self.assertEqual((root / ".zeuz-history" / digest).read_bytes(), b"old\r\n\xff")
        self.request("PUT", "/v1/programs/content", {"path": "O2.nc", "content": "mobile edit"})
        self.sync.cycle()
        self.assertEqual((root / "O2.nc").read_text(), "mobile edit")
        program.unlink()
        self.sync.cycle()
        self.assertTrue((root / "O2.nc").exists())
        program.write_bytes(b"new\r\n")
        (root / "O2.nc").unlink()
        self.sync.cycle()
        self.assertEqual((root / "O2.nc").read_bytes(), b"new\r\n")

    def test_conflict_survives_restart_and_resolution_archives_both(self):
        self.sync.cycle()
        self.registry.save({**self.registry.get("lathe"), "baudrate": 4800})
        machines.save_machine({**machines.get_machine("lathe"), "baudrate": 19200})
        restarted = WorkshopSync(self.config, self.registry)
        restarted.cycle()
        self.assertEqual(len(restarted.conflicts), 1)
        self.assertEqual(self.registry.get("lathe")["baudrate"], 4800)
        self.assertEqual(machines.get_machine("lathe")["baudrate"], 19200)
        restarted.resolve("lathe", "127.0.0.1", self.pi.server_port, True)
        restarted.cycle()
        self.assertEqual(self.registry.get("lathe")["baudrate"], 19200)
        self.assertEqual(restarted.conflicts, [])
        history = json.loads(restarted.path.read_text())["conflict_history"][-1]
        self.assertEqual(history["local"]["baudrate"], 4800)
        self.assertEqual(history["device"]["baudrate"], 19200)

    def test_offline_retries_without_reset_and_stale_revision_rejected(self):
        with patch.object(self.sync.proxy, "forward", side_effect=OSError("offline")):
            self.sync.cycle()
        self.assertTrue(self.sync.status.startswith("Pendiente"))
        self.sync.cycle()
        self.assertTrue(self.sync.status.startswith("Sincronizado"), self.sync.status)
        stale = machines.get_machine("lathe")
        machines.save_machine({**stale, "baudrate": 4800})
        with self.assertRaises(urllib.error.HTTPError):
            self.request("POST", "/api/workshop/machine", {"machine": stale, "expected_revision": stale["revision"]})
        local = self.registry.get("lathe")
        self.registry.save({**local, "name": "Changed"})
        with self.assertRaises(MachineConflict): self.registry.save(local)

    def test_name_persists_and_path_escape_rejected(self):
        self.request("POST", "/api/workshop/configure", {"name": "Fresadora este"})
        self.assertEqual(self.request("GET", "/api/workshop/info")["name"], "Fresadora este")
        raw = b"bad"
        with self.assertRaises(urllib.error.HTTPError):
            self.request("POST", "/api/workshop/mirror", {"path": "../escape.nc", "data": base64.b64encode(raw).decode(), "sha256": hashlib.sha256(raw).hexdigest()})
        self.assertFalse((self.root / "escape.nc").exists())

    def test_last_machine_deletion_propagates(self):
        self.sync.cycle()
        self.registry.delete("lathe")
        self.sync.cycle()
        self.assertEqual(machines.load_machines(), [])

    def test_pi_routes_mobile_to_second_pi_without_agent(self):
        remote_machine = {**serial_profile(self.machine), "id": "mill", "name": "Fresa", "revision": 3}
        calls = []
        class Destination(BaseHTTPRequestHandler):
            def do_GET(self):
                self.send_response(200)
                self.end_headers()
                self.wfile.write(json.dumps([remote_machine]).encode())
            def do_POST(self):
                calls.append((self.path, json.loads(self.rfile.read(int(self.headers["Content-Length"])))))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b'{"ok":true}')
            def log_message(self, *args): pass
        destination = ThreadingHTTPServer(("127.0.0.1", 0), Destination)
        thread = threading.Thread(target=destination.serve_forever, daemon=True)
        thread.start()
        try:
            self.sync.cycle()
            workshop.configure({"machine_routes": [{"host": "127.0.0.1", "port": destination.server_port, "machines": [{**remote_machine, "catalog_id": "mill"}]}]})
            self.assertEqual(len(self.request("GET", "/v1/dnc/machines")), 2)
            self.request("POST", "/v1/dnc/send", {"path": "O1.nc", "machine_id": "mill"})
            self.assertEqual(calls[-1][0], "/api/send")
            self.assertEqual(calls[-1][1]["machine"]["revision"], 3)
        finally:
            destination.shutdown()
            destination.server_close()
            thread.join()

    def test_remote_recreation_after_confirmed_deletion_is_imported(self):
        self.sync.cycle()
        self.registry.delete("lathe")
        self.sync.cycle()
        machines.save_machine({**serial_profile(self.machine), "id": "", "name": "lathe"})
        self.sync.cycle()
        self.assertEqual(self.registry.get("lathe")["name"], "lathe")

    def test_duplicate_device_id_gets_stable_catalog_identity(self):
        self.sync.cycle()
        self.registry.save({**self.machine, "id": "lathe-other", "dnc_host": "another.invalid", "dnc_machine_id": "lathe"})
        # Emulate a second device whose local ID is also lathe.
        from zeuzagent.dnc_proxy import DNCEndpoint
        with patch.object(self.sync, "request", return_value=[{**serial_profile(self.machine), "revision": 1}]):
            self.sync.sync_machines(DNCEndpoint("third.local", 5000))
        values = [m for m in self.registry.list() if m["dnc_host"] == "third.local"]
        self.assertEqual(len(values), 1)
        self.assertNotEqual(values[0]["id"], "lathe")
        self.assertEqual(values[0]["dnc_machine_id"], "lathe")

    def test_revision_is_portable_and_exact_in_qml(self):
        self.sync.cycle()
        agent_revision = self.registry.get("lathe")["revision"]
        device_revision = machines.get_machine("lathe")["revision"]
        self.assertEqual(agent_revision, device_revision)
        self.assertEqual(int(float(agent_revision)), agent_revision)
        stale = self.registry.get("lathe")
        machines.save_machine({**machines.get_machine("lathe"), "baudrate": 38400})
        with self.assertRaises(urllib.error.HTTPError):
            self.request("POST", "/v1/dnc/machine/save", stale)

    def test_mobile_preview_is_truncated_without_changing_file(self):
        self.sync.cycle()
        raw = b"O0001\n" * 400000
        path = self.root / "pi-programs" / "large.nc"
        path.write_bytes(raw)
        document = self.request("GET", "/v1/programs/content?path=large.nc")
        self.assertTrue(document["truncated"])
        self.assertEqual(path.read_bytes(), raw)

    def test_edit_during_cycle_remains_pending_until_next_confirmation(self):
        original = self.sync.proxy.forward
        dirty = False
        def forward(*args, **kwargs):
            nonlocal dirty
            result = original(*args, **kwargs)
            if not dirty:
                dirty = True
                self.sync.mark_dirty()
            return result
        with patch.object(self.sync.proxy, "forward", side_effect=forward):
            self.sync.cycle()
        self.assertTrue(self.sync.status.startswith("Pendiente"))
        self.sync.cycle()
        self.assertTrue(self.sync.status.startswith("Sincronizado"))
