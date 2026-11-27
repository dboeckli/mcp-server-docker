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
    assert is_tool_enabled(ToolAnnotations(), settings)
    assert is_tool_enabled(None, settings)


def test_read_only_hides_write_and_unannotated_tools():
    settings = ServerSettings(read_only=True)
    assert is_tool_enabled(ToolAnnotations(read_only_hint=True), settings)
    assert not is_tool_enabled(ToolAnnotations(read_only_hint=False), settings)
    assert not is_tool_enabled(ToolAnnotations(), settings)
    assert not is_tool_enabled(None, settings)


@pytest.mark.parametrize(
    "env_key",
    ["MCP_SERVER_DOCKER_DISABLE_DESTRUCTIVE", "MCP_SERVER_DOCKER_NO_DESTRUCTIVE"],
)
@pytest.mark.parametrize("value", ["1", "true", "yes", "on"])
def test_env_enables_disable_destructive(env_key, value):
    settings = ServerSettings.from_env_and_argv(env={env_key: value}, argv=[])
    assert settings.disable_destructive is True


@pytest.mark.parametrize("flag", ["--disable-destructive", "--no-destructive"])
def test_flag_enables_disable_destructive(flag):
    settings = ServerSettings.from_env_and_argv(env={}, argv=[flag])
    assert settings.disable_destructive is True


def test_tool_lists_accept_comma_separated_and_repeated_flags():
    settings = ServerSettings.from_env_and_argv(
        env={},
        argv=[
            "--enable-tools",
            "docker_version,docker_system_info",
            "--enable-tools=docker_events_list",
            "--disable-tools",
            "docker_stop_container",
        ],
    )
    assert settings.enabled_tools == {
        "docker_version",
        "docker_system_info",
        "docker_events_list",
    }
    assert settings.disabled_tools == {"docker_stop_container"}


def test_tool_lists_accept_env_values():
    settings = ServerSettings.from_env_and_argv(
        env={
            "MCP_SERVER_DOCKER_ENABLE_TOOLS": "docker_version, docker_system_info",
            "MCP_SERVER_DOCKER_DISABLE_TOOLS": "docker_stop_container,",
        },
        argv=[],
    )
    assert settings.enabled_tools == {"docker_version", "docker_system_info"}
    assert settings.disabled_tools == {"docker_stop_container"}


def test_conflicting_tool_lists_abort_startup():
    with pytest.raises(SystemExit) as error:
        ServerSettings.from_env_and_argv(
            env={},
            argv=[
                "--enable-tools",
                "docker_version",
                "--disable-tools",
                "docker_version",
            ],
        )
    assert "docker_version" in str(error.value)


@pytest.mark.parametrize(
    "argv",
    [["--enable-tools"], ["--enable-tools", "--read-only"], ["--disable-tools="]],
)
def test_tool_list_flags_require_a_value(argv):
    with pytest.raises(SystemExit):
        ServerSettings.from_env_and_argv(env={}, argv=argv)


def test_disable_destructive_keeps_mutations_and_hides_destructive_tools():
    settings = ServerSettings(disable_destructive=True)
    assert is_tool_enabled(ToolAnnotations(read_only_hint=True), settings)
    assert is_tool_enabled(ToolAnnotations(destructive_hint=False), settings)
    assert not is_tool_enabled(ToolAnnotations(destructive_hint=True), settings)
    assert is_tool_enabled(None, settings)


def test_read_only_wins_over_disable_destructive():
    settings = ServerSettings(read_only=True, disable_destructive=True)
    assert is_tool_enabled(ToolAnnotations(read_only_hint=True), settings)
    assert not is_tool_enabled(ToolAnnotations(read_only_hint=False), settings)


def test_explicit_enable_overrides_read_only_and_destructive_filter():
    settings = ServerSettings(
        read_only=True,
        disable_destructive=True,
        enabled_tools=frozenset({"docker_remove_container"}),
    )
    assert is_tool_enabled(
        ToolAnnotations(read_only_hint=False, destructive_hint=True),
        settings,
        "docker_remove_container",
    )


def test_explicit_disable_wins_over_read_only():
    settings = ServerSettings(
        read_only=True, disabled_tools=frozenset({"docker_version"})
    )
    assert not is_tool_enabled(
        ToolAnnotations(read_only_hint=True), settings, "docker_version"
    )
