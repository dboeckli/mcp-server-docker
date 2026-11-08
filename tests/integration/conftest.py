import shutil
import subprocess
import uuid

import pytest

import mcp_server_docker.server as server_module


@pytest.fixture(scope="session")
def docker_daemon():
    if shutil.which("docker") is None:
        pytest.skip("docker CLI not found")
    result = subprocess.run(
        ["docker", "info"], capture_output=True, text=True, check=False
    )
    if result.returncode != 0:
        pytest.skip(f"docker daemon not reachable: {result.stderr.strip()}")
    return True


@pytest.fixture(scope="session")
def buildx_history_ready(docker_daemon):
    result = subprocess.run(
        ["docker", "buildx", "history", "ls"],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        pytest.skip(
            f"buildx history not available: {result.stderr.strip() or result.stdout.strip()}"
        )
    return True


@pytest.fixture
def build_record(buildx_history_ready, tmp_path):
    unique = uuid.uuid4().hex[:12]
    context = tmp_path / f"ctx-{unique}"
    context.mkdir()
    (context / "Dockerfile").write_text(
        "FROM scratch\nCOPY hello.txt /hello.txt\n", encoding="utf-8"
    )
    (context / "hello.txt").write_text("hello\n", encoding="utf-8")
    tag = f"mcp-server-docker-it:{unique}"

    before = {record["ref"] for record in server_module.buildx_history()}
    build = subprocess.run(
        ["docker", "buildx", "build", "-t", tag, "--progress", "plain", str(context)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert build.returncode == 0, build.stderr

    new_records = [
        record
        for record in server_module.buildx_history()
        if record["ref"] not in before
    ]
    record = next((r for r in new_records if r.get("name") == context.name), None)
    if record is None:
        pytest.skip("buildx did not record build history for the test build")

    ref = record["ref"]
    build_id = ref.rsplit("/", 1)[-1]
    yield {"ref": ref, "build_id": build_id, "tag": tag, "name": context.name}

    subprocess.run(
        ["docker", "buildx", "history", "rm", build_id],
        capture_output=True,
        text=True,
        check=False,
    )
    subprocess.run(
        ["docker", "image", "rm", "-f", tag],
        capture_output=True,
        text=True,
        check=False,
    )
