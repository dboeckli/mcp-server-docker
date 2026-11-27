import copy
import os
import re
from typing import Any

_REDACTED = "<redacted>"
_REDACTED_PATH = "<redacted-path>"
_ENV_SECTIONS = ("Config", "ContainerConfig")
_URL_USERINFO = re.compile(r"(?P<scheme>[A-Za-z][A-Za-z0-9+.-]*://)[^/@\s]+@")
_SOCKET = re.compile(r"(?P<scheme>unix|npipe)://[^\s)'\",]+")
_PATH = re.compile(r"(?<![\w:/])(?:[A-Za-z]:[\\/]|/)[^\s)'\":,]+")
_ENV_PREFIX = "DOCKER_"
_MIN_ENV_VALUE_LENGTH = 4


def _redact_entry(entry: Any) -> str:
    if not isinstance(entry, str) or "=" not in entry:
        return _REDACTED
    key, _, _ = entry.partition("=")
    return f"{key}={_REDACTED}"


def redact_env(attrs: dict[str, Any]) -> dict[str, Any]:
    redacted = copy.deepcopy(attrs)
    for section in _ENV_SECTIONS:
        config = redacted.get(section)
        if not isinstance(config, dict):
            continue
        env = config.get("Env")
        if isinstance(env, list):
            config["Env"] = [_redact_entry(entry) for entry in env]
    return redacted


def redact_error(message: str) -> str:
    """Remove host, socket, certificate paths and Docker env values from errors."""
    redacted = message
    for name, value in os.environ.items():
        if name.startswith(_ENV_PREFIX) and len(value) >= _MIN_ENV_VALUE_LENGTH:
            redacted = redacted.replace(value, _REDACTED)
    redacted = _URL_USERINFO.sub(r"\g<scheme>" + _REDACTED + "@", redacted)
    redacted = _SOCKET.sub(r"\g<scheme>://" + _REDACTED, redacted)
    return _PATH.sub(_REDACTED_PATH, redacted)
