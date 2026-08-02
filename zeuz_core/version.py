from __future__ import annotations

from pathlib import Path


SYSTEM_VERSION_PATH = Path("/etc/zeuz/version")
SOURCE_VERSION_PATH = Path(__file__).resolve().parents[1] / "VERSION"


def installed_version() -> str:
    """Devuelve la versión realmente instalada, con respaldo para desarrollo."""

    for path in (SYSTEM_VERSION_PATH, SOURCE_VERSION_PATH):
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError:
            continue
        if value:
            return value
    return "desconocida"
