import subprocess
import uuid

import pytest

import mcp_server_docker.server as server_module


@pytest.fixture
def created_volume(docker_daemon):
    name = f"mcp-server-docker-events-{uuid.uuid4().hex[:12]}"
    created = subprocess.run(
        ["docker", "volume", "create", name],
        capture_output=True,
        text=True,
        check=False,
    )
    assert created.returncode == 0, created.stderr
    try:
        yield name
    finally:
        subprocess.run(
            ["docker", "volume", "rm", "-f", name],
            capture_output=True,
            text=True,
            check=False,
        )


@pytest.mark.integration
def test_events_list_reports_a_real_volume_event(created_volume):
    result = server_module.events_list(
        window_seconds=60,
        filters=server_module.ListEventsFilters(type=["volume"], event=["create"]),
    )
    assert result["truncated"] is False
    assert result["since"] < result["until"]
    assert any(
        event["Action"] == "create" and event["Actor"]["ID"] == created_volume
        for event in result["events"]
    )


@pytest.mark.integration
def test_events_list_window_is_bounded_and_returns_promptly(created_volume):
    result = server_module.events_list(window_seconds=1, limit=1)
    assert result["until"] - result["since"] == 1
    assert result["count"] <= 1
    assert len(result["events"]) <= 1
    assert isinstance(result["truncated"], bool)


@pytest.mark.integration
def test_events_list_survives_a_filter_with_no_matches(created_volume):
    result = server_module.events_list(
        window_seconds=60,
        filters=server_module.ListEventsFilters(container=["does-not-exist"]),
    )
    assert result["events"] == []
    assert result["count"] == 0
    assert result["truncated"] is False
    assert "truncated_reason" not in result
