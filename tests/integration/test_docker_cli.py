import pytest

import mcp_server_docker.server as server_module


@pytest.mark.integration
def test_buildx_logs_returns_logs_for_full_ref(build_record):
    logs = server_module.buildx_logs(build_record["ref"])
    assert logs.strip()
    assert "hello.txt" in logs


@pytest.mark.integration
def test_buildx_logs_returns_logs_for_bare_id(build_record):
    logs = server_module.buildx_logs(build_record["build_id"])
    assert logs.strip()
    assert "hello.txt" in logs


@pytest.mark.integration
def test_buildx_logs_unknown_ref_raises(build_record):
    with pytest.raises(RuntimeError, match="no record found"):
        server_module.buildx_logs("mcp-server-docker-does-not-exist")


@pytest.mark.integration
def test_run_docker_merges_stderr_for_buildx_logs(build_record):
    output = server_module._run_docker(
        "buildx", "history", "logs", build_record["build_id"], combine_stderr=True
    )
    assert output.strip()
    assert "hello.txt" in output
