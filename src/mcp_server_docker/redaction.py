import copy
from typing import Any

_REDACTED = "<redacted>"
_ENV_SECTIONS = ("Config", "ContainerConfig")


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
