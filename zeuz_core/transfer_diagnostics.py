"""Bounded local history for serial outcomes, including across reboots."""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import sys


DEFAULT_LOG_PATH = Path("/var/lib/zeuz/transfer-errors.log")
MAX_LOG_BYTES = 128 * 1024
BACKUP_COUNT = 2


def configure_transfer_diagnostics(path: Path | None = None) -> bool:
    """Keep transfer boundaries in a small rotating file and stderr."""
    logger = logging.getLogger("zeuz.serial")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
    tagged = {getattr(handler, "_zeuz_transfer_handler", None): handler for handler in logger.handlers}
    if "stderr" not in tagged:
        stderr = logging.StreamHandler(sys.stderr)
        stderr._zeuz_transfer_handler = "stderr"
        stderr.setFormatter(formatter)
        logger.addHandler(stderr)

    target = Path(path or DEFAULT_LOG_PATH).resolve()
    current = tagged.get("file")
    if current is not None:
        if current.baseFilename == str(target):
            return True
        logger.removeHandler(current)
        current.close()
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        persistent = RotatingFileHandler(target, maxBytes=MAX_LOG_BYTES,
                                         backupCount=BACKUP_COUNT, encoding="utf-8")
    except OSError:
        logger.error("No se pudo abrir el registro de errores seriales; se conserva el diagnóstico en stderr",
                     exc_info=True)
        return False
    persistent._zeuz_transfer_handler = "file"
    persistent.setFormatter(formatter)
    logger.addHandler(persistent)
    return True
