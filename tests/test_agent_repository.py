import tempfile
import threading
import unittest
from pathlib import Path

from zeuz_core.pair_agent import pair, write_runtime
from zeuz_core.programs import AgentConnection, AgentProgramRepository, ProgramSourceError
from zeuz_core.settings import RuntimeSettings
from zeuzagent.config import AgentConfig
from zeuzagent.library import ProgramLibrary
from zeuzagent.server import create_server


class AgentRepositoryIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        config = AgentConfig(
            name="Agente de prueba",
            programs_dir=self.temp.name,
            host="127.0.0.1",
            port=0,
            api_token="token-integracion",
            pairing_code="123456",
            discovery=False,
        )
        self.server = create_server(config, ProgramLibrary(Path(self.temp.name)))
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.repository = AgentProgramRepository(
            AgentConnection(
                f"http://127.0.0.1:{self.server.server_port}",
                "token-integracion",
            )
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp.cleanup()

    def test_pi_can_edit_program_through_agent(self) -> None:
        created = self.repository.create("", "O5000.nc")
        self.repository.write(created["path"], "O5000\r\nM30\r\n")
        loaded = self.repository.read("O5000.nc")
        self.assertEqual(loaded["content"], "O5000\r\nM30\r\n")
        self.assertEqual(self.repository.list()["entries"][0]["name"], "O5000.nc")
        materialized = self.repository.materialize("O5000.nc")
        try:
            self.assertEqual(materialized.read_bytes(), b"O5000\r\nM30\r\n")
        finally:
            materialized.unlink()

    def test_wrong_token_is_rejected(self) -> None:
        other = AgentProgramRepository(
            AgentConnection(
                f"http://127.0.0.1:{self.server.server_port}",
                "token-incorrecto",
            )
        )
        with self.assertRaisesRegex(ProgramSourceError, "Emparejamiento"):
            other.list()

    def test_pairing_creates_working_runtime_settings(self) -> None:
        base_url = f"http://127.0.0.1:{self.server.server_port}"
        paired = pair(base_url, "123456")
        with tempfile.TemporaryDirectory() as settings_directory:
            runtime_path = Path(settings_directory) / "runtime.json"
            write_runtime(runtime_path, base_url, paired["token"])
            repository = RuntimeSettings.load(runtime_path).repository()
            self.assertEqual(repository.list("")["entries"], [])


if __name__ == "__main__":
    unittest.main()
