import pytest


@pytest.mark.integration
def test_build_record_exposes_its_own_ref(build_record):
    assert build_record["build_id"]
    assert build_record["ref"].endswith(build_record["build_id"])
    assert build_record["tag"].startswith("mcp-server-docker-it:")
    assert build_record["name"].startswith("ctx-")
