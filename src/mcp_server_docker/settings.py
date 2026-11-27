import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field

from mcp.types import ToolAnnotations

_READ_ONLY_ENV = "MCP_SERVER_DOCKER_READ_ONLY"
_READ_ONLY_FLAG = "--read-only"
_DISABLE_DESTRUCTIVE_ENVS = (
    "MCP_SERVER_DOCKER_DISABLE_DESTRUCTIVE",
    "MCP_SERVER_DOCKER_NO_DESTRUCTIVE",
)
_DISABLE_DESTRUCTIVE_FLAGS = ("--disable-destructive", "--no-destructive")
_ENABLE_TOOLS_ENV = "MCP_SERVER_DOCKER_ENABLE_TOOLS"
_DISABLE_TOOLS_ENV = "MCP_SERVER_DOCKER_DISABLE_TOOLS"
_ENABLE_TOOLS_FLAG = "--enable-tools"
_DISABLE_TOOLS_FLAG = "--disable-tools"
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ServerSettings:
    read_only: bool = False
    disable_destructive: bool = False
    enabled_tools: frozenset[str] = field(default_factory=frozenset)
    disabled_tools: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def from_env_and_argv(
        cls,
        env: Mapping[str, str] | None = None,
        argv: Iterable[str] | None = None,
    ) -> "ServerSettings":
        environment = os.environ if env is None else env
        arguments = list(sys.argv[1:] if argv is None else argv)
        enabled = _tool_names(
            environment.get(_ENABLE_TOOLS_ENV, ""), arguments, _ENABLE_TOOLS_FLAG
        )
        disabled = _tool_names(
            environment.get(_DISABLE_TOOLS_ENV, ""), arguments, _DISABLE_TOOLS_FLAG
        )
        conflicts = enabled & disabled
        if conflicts:
            raise SystemExit(
                "Conflicting tool filters: "
                f"{', '.join(sorted(conflicts))} is both enabled and disabled"
            )
        return cls(
            read_only=_is_truthy(environment.get(_READ_ONLY_ENV))
            or _READ_ONLY_FLAG in arguments,
            disable_destructive=any(
                _is_truthy(environment.get(name)) for name in _DISABLE_DESTRUCTIVE_ENVS
            )
            or any(flag in arguments for flag in _DISABLE_DESTRUCTIVE_FLAGS),
            enabled_tools=frozenset(enabled),
            disabled_tools=frozenset(disabled),
        )


def _is_truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in _TRUTHY


def _tool_names(env_value: str, arguments: list[str], flag: str) -> set[str]:
    names = _split_names(env_value)
    for index, argument in enumerate(arguments):
        if argument.startswith(f"{flag}="):
            names.update(_split_names(argument.split("=", 1)[1], flag))
        elif argument == flag:
            value = arguments[index + 1] if index + 1 < len(arguments) else ""
            if not value or value.startswith("-"):
                raise SystemExit(f"{flag} requires a comma-separated tool list")
            names.update(_split_names(value, flag))
    return names


def _split_names(value: str, flag: str = "") -> set[str]:
    names = {name.strip() for name in value.split(",") if name.strip()}
    if flag and not names:
        raise SystemExit(f"{flag} requires a comma-separated tool list")
    return names


def is_tool_enabled(
    annotations: ToolAnnotations | None,
    settings: ServerSettings,
    name: str | None = None,
) -> bool:
    if name is not None and name in settings.enabled_tools:
        return True
    if name is not None and name in settings.disabled_tools:
        return False
    if settings.read_only:
        return annotations is not None and annotations.read_only_hint is True
    if settings.disable_destructive:
        return annotations is None or annotations.destructive_hint is not True
    return True
