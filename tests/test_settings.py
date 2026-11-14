import pytest
from mcp.types import ToolAnnotations

from mcp_server_docker.settings import ServerSettings, is_tool_enabled


@pytest.mark.parametrize("value", ["1", "true", "TRUE", "yes", "on"])
def test_env_truthy_values_enable_read_only(value):
    settings = ServerSettings.from_env_and_argv(
        env={"MCP_SERVER_DOCKER_READ_ONLY": value}, argv=[]
    )
    assert settings.read_only is True


@pytest.mark.parametrize("value", ["", "0", "false", "no", "off", "2"])
def test_env_other_values_keep_write_mode(value):
    settings = ServerSettings.from_env_and_argv(
        env={"MCP_SERVER_DOCKER_READ_ONLY": value}, argv=[]
    )
    assert settings.read_only is False


def test_cli_flag_and_env_are_ored():
    assert ServerSettings.from_env_and_argv(env={}, argv=["--read-only"]).read_only
    assert not ServerSettings.from_env_and_argv(
        env={}, argv=["--read-only=true"]
    ).read_only
    assert ServerSettings.from_env_and_argv(
        env={"MCP_SERVER_DOCKER_READ_ONLY": "1"}, argv=[]
    ).read_only


def test_default_mode_enables_every_tool():
    settings = ServerSettings()
    assert is_tool_enabled("create_container", ToolAnnotations(), settings)
    assert is_tool_enabled("create_container", None, settings)


def test_read_only_hides_write_and_unannotated_tools():
    settings = ServerSettings(read_only=True)
    assert is_tool_enabled(
        "list_containers", ToolAnnotations(read_only_hint=True), settings
    )
    assert not is_tool_enabled(
        "create_container", ToolAnnotations(read_only_hint=False), settings
    )
    assert not is_tool_enabled("create_container", ToolAnnotations(), settings)
    assert not is_tool_enabled("create_container", None, settings)
