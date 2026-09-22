"""Management authorization is tied to the paired Agent, not a discoverable PIN."""
import hmac
import json
from .settings import DEFAULT_SETTINGS_PATH


def paired_token():
    try:
        value = json.loads(DEFAULT_SETTINGS_PATH.read_text())
    except (FileNotFoundError, ValueError, OSError):
        return ""
    return str(value.get("paired_agent", {}).get("token") or value.get("program_source", {}).get("token") or "")


def authorized(header):
    token = paired_token()
    return bool(token) and hmac.compare_digest(str(header or ""), "Bearer " + token)
