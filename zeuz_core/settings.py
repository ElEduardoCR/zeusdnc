from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path

from .programs import AgentConnection, AgentProgramRepository, LocalProgramRepository, ProgramRepository


ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SETTINGS_PATH = Path(
    os.environ.get("ZEUZ_CONFIG_PATH", ROOT / "config" / "runtime.json")
)


@dataclass(frozen=True)
class RuntimeSettings:
    source_type: str
    local_path: str = "/var/lib/zeuz/programs"
    agent_url: str = ""
    agent_token: str = ""

    @classmethod
    def load(cls, path: Path = DEFAULT_SETTINGS_PATH) -> "RuntimeSettings":
        data: dict = {}
        if path.exists():
            with path.open("r", encoding="utf-8") as handle:
                data = json.load(handle)
        source = data.get("program_source", {})
        source_type = os.environ.get("ZEUZ_PROGRAM_SOURCE", source.get("type", "local"))
        local_path = os.environ.get(
            "ZEUZ_PROGRAMS_DIR",
            source.get("path", "/var/lib/zeuz/programs"),
        )
        agent_url = os.environ.get("ZEUZ_AGENT_URL", source.get("url", ""))
        agent_token = os.environ.get("ZEUZ_AGENT_TOKEN", source.get("token", ""))
        return cls(
            source_type=source_type,
            local_path=local_path,
            agent_url=agent_url,
            agent_token=agent_token,
        )

    def repository(self) -> ProgramRepository:
        if self.source_type == "agent":
            if not self.agent_url or not self.agent_token:
                raise ValueError("Faltan url/token de Zeuz Agent en config/runtime.json")
            return AgentProgramRepository(AgentConnection(self.agent_url, self.agent_token))
        return LocalProgramRepository(Path(self.local_path))
