import os
import sys
from collections.abc import Iterable, Mapping
from dataclasses import dataclass

from mcp.types import ToolAnnotations

_READ_ONLY_ENV = "MCP_SERVER_DOCKER_READ_ONLY"
_READ_ONLY_FLAG = "--read-only"
_TRUTHY = {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class ServerSettings:
    read_only: bool = False

    @classmethod
    def from_env_and_argv(
        cls,
        env: Mapping[str, str] | None = None,
        argv: Iterable[str] | None = None,
    ) -> "ServerSettings":
        environment = os.environ if env is None else env
        arguments = list(sys.argv[1:] if argv is None else argv)
        env_enabled = environment.get(_READ_ONLY_ENV, "").strip().lower() in _TRUTHY
        return cls(read_only=env_enabled or _READ_ONLY_FLAG in arguments)


def is_tool_enabled(
    name: str,
    annotations: ToolAnnotations | None,
    settings: ServerSettings,
) -> bool:
    if not settings.read_only:
        return True
    return annotations is not None and annotations.read_only_hint is True
