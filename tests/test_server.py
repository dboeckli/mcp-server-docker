import json
import subprocess
import sys
import threading
from pathlib import Path
from types import SimpleNamespace
from typing import Any, ClassVar

import docker
import pytest
from mcp.client import Client
from mcp.client.stdio import StdioServerParameters, stdio_client
from mcp.shared.exceptions import MCPError

import mcp_server_docker.server as server_module
from mcp_server_docker.server import app


class Object:
    id = "object-id"
    name = "object-name"
    short_id = "object-id"
    status = "running"
    image = None
    ports: ClassVar = {}
    attrs: ClassVar = {"Config": {}, "State": {}, "NetworkSettings": {}}
    logs_payload: ClassVar = b"line\n"

    def __init__(self, calls: list[tuple[str, Any]]):
        self.calls = calls

    def logs(self, **kwargs):
        self.calls.append(("object.logs", kwargs))
        return type(self).logs_payload

    def stats(self, **kwargs):
        self.calls.append(("object.stats", kwargs))
        return {"cpu": 1}

    def top(self):
        self.calls.append(("object.top", None))
        return {"Titles": ["PID", "CMD"], "Processes": [["1", "nginx"]]}

    def start(self):
        self.calls.append(("object.start", None))

    def stop(self):
        self.calls.append(("object.stop", None))

    def remove(self, **kwargs):
        self.calls.append(("object.remove", kwargs))


class Collection:
    def __init__(self, calls: list[tuple[str, Any]], name: str):
        self.calls, self.name = calls, name
        self.prune_payload: dict[str, Any] = {}

    def list(self, **kwargs):
        self.calls.append((f"{self.name}.list", kwargs))
        return []

    def prune(self, **kwargs):
        self.calls.append((f"{self.name}.prune", kwargs))
        return self.prune_payload

    def get(self, name):
        self.calls.append((f"{self.name}.get", name))
        return Object(self.calls)

    def create(self, **kwargs):
        self.calls.append((f"{self.name}.create", kwargs))
        return Object(self.calls)

    def run(self, **kwargs):
        self.calls.append((f"{self.name}.run", kwargs))
        if kwargs.get("detach") is False:
            return b"attached\xff\n"
        return Object(self.calls)


class Images(Collection):
    def pull(self, repository, **kwargs):
        self.calls.append(("images.pull", (repository, kwargs)))
        return Object(self.calls)

    def push(self, repository, **kwargs):
        self.calls.append(("images.push", (repository, kwargs)))
        return []

    def build(self, **kwargs):
        self.calls.append(("images.build", kwargs))
        return Object(self.calls), [{"stream": "built"}]

    def remove(self, **kwargs):
        self.calls.append(("images.remove", kwargs))


class Response:
    def __init__(self, payload: Any, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def json(self) -> Any:
        return self._payload


class Api:
    def __init__(self, calls: list[tuple[str, Any]]):
        self.calls = calls
        self.payload: Any = []
        self.base_url = "http://docker"
        self.status_code = 200
        self.error: Exception | None = None
        self.timeouts: list[float | None] = []
        self.prune_builds_payload: dict[str, Any] = {}
        self.exec_output: list[bytes] = []
        self.exec_exit_code: int | None = 0
        self.exec_stream: Any = None

    def _url(self, path: str) -> str:
        return f"http://docker{path}"

    def prune_builds(self, **params: Any) -> dict[str, Any]:
        self.calls.append(("api.prune_builds", params))
        return self.prune_builds_payload

    def exec_create(
        self, container: str, cmd: list[str], **kwargs: Any
    ) -> dict[str, Any]:
        self.calls.append(("api.exec_create", (container, cmd, kwargs)))
        return {"Id": "exec-1"}

    def exec_start(self, exec_id: str, **kwargs: Any) -> Any:
        self.calls.append(("api.exec_start", (exec_id, kwargs)))
        if self.exec_stream is not None:
            return self.exec_stream
        return iter(self.exec_output)

    def exec_inspect(self, exec_id: str) -> dict[str, Any]:
        self.calls.append(("api.exec_inspect", exec_id))
        return {"ExitCode": self.exec_exit_code}

    def get(
        self,
        url: str,
        params: dict[str, Any] | None = None,
        timeout: float | None = None,
    ) -> Response:
        self.calls.append(("api.get", (url, params)))
        self.timeouts.append(timeout)
        if self.error is not None:
            raise self.error
        return Response(self.payload, self.status_code)

    def _result(
        self, response: Response, json: bool = False, binary: bool = False
    ) -> Any:
        return response.json() if json else response


class Docker:
    def __init__(self):
        self.calls: list[tuple[str, Any]] = []
        self.api = Api(self.calls)
        self.containers = Collection(self.calls, "containers")
        self.images = Images(self.calls, "images")
        self.networks = Collection(self.calls, "networks")
        self.volumes = Collection(self.calls, "volumes")
        self.closed = False

    def close(self):
        self.closed = True

    def version(self):
        self.calls.append(("version", None))
        return {"Version": "29.9.3", "ApiVersion": "1.52"}

    def info(self):
        self.calls.append(("info", None))
        return {
            "ServerVersion": "29.9.3",
            "Driver": "overlay2",
            "DriverStatus": [["Backing Filesystem", "extfs"]],
            "NCPU": 8,
            "MemTotal": 16_000_000_000,
            "Containers": 3,
            "Images": 5,
            "HttpProxy": "http://user:secret@proxy",
            "RegistryConfig": {"IndexConfigs": {}},
        }

    def call(self, name: str) -> Any:
        return next(value for key, value in reversed(self.calls) if key == name)


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture
def docker_client(monkeypatch):
    client = Docker()
    monkeypatch.setattr(
        server_module,
        "docker_to_dict",
        lambda _obj, overrides=None, format="full": {
            "id": "object-id",
            **(overrides or {}),
        },
    )
    monkeypatch.setattr(server_module.docker, "from_env", lambda: client)
    yield client
    assert client.closed


@pytest.fixture
def server(docker_client):
    return app


@pytest.mark.anyio
async def test_lifespan_starts_without_reachable_daemon(monkeypatch):
    client = Docker()
    calls = []

    def fake_from_env(**kwargs):
        calls.append(kwargs)
        if "version" not in kwargs:
            raise docker.errors.DockerException("no daemon")
        return client

    monkeypatch.setattr(server_module.docker, "from_env", fake_from_env)

    async with server_module.lifespan(None) as context:
        assert context.docker is client
    assert client.closed
    assert calls == [{}, {"version": docker.constants.DEFAULT_DOCKER_API_VERSION}]


class FakeProcess:
    def __init__(self, stdout: str = "", stderr: str = "", returncode: int = 0):
        self.stdout = stdout
        self.stderr = stderr
        self.returncode = returncode


@pytest.fixture
def docker_cli(monkeypatch):
    cli = SimpleNamespace(calls=[], kwargs=[], responses=[], metadata=None)

    def fake_run(command, **kwargs):
        if kwargs.get("capture_output") and ("stdout" in kwargs or "stderr" in kwargs):
            raise ValueError(
                "stdout and stderr arguments may not be used with capture_output"
            )
        cli.calls.append(command)
        cli.kwargs.append(kwargs)
        process = cli.responses.pop(0)
        if isinstance(process, BaseException):
            raise process
        if cli.metadata is not None and "--metadata-file" in command:
            path = command[command.index("--metadata-file") + 1]
            Path(path).write_text(json.dumps(cli.metadata), encoding="utf-8")
        if kwargs.get("stderr") is subprocess.STDOUT:
            return FakeProcess(
                stdout=process.stdout + (process.stderr or ""),
                stderr=None,
                returncode=process.returncode,
            )
        return process

    monkeypatch.setattr(server_module.subprocess, "run", fake_run)
    monkeypatch.setattr(server_module.shutil, "which", lambda _name: "/usr/bin/docker")
    return cli


def test_run_docker_decodes_utf8_and_replaces_undecodable_bytes(monkeypatch):
    monkeypatch.setattr(server_module.shutil, "which", lambda _name: sys.executable)
    output = server_module._run_docker(
        "-c", "import sys; sys.stdout.buffer.write('grün→'.encode() + b'\\x90')"
    )
    assert output == "grün→\ufffd"


def test_run_docker_replaces_undecodable_bytes_in_errors(monkeypatch):
    monkeypatch.setattr(server_module.shutil, "which", lambda _name: sys.executable)
    with pytest.raises(RuntimeError) as excinfo:
        server_module._run_docker(
            "-c", "import sys; sys.stderr.buffer.write(b'bad\\x90byte'); sys.exit(1)"
        )
    assert "bad\ufffdbyte" in str(excinfo.value)


@pytest.mark.anyio
async def test_buildx_list_parses_json_and_json_lines(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(FakeProcess(stdout='[{"name": "a"}]'))
        result = await client.call_tool("docker_buildx_list", {})
        assert result.structured_content == {"result": [{"name": "a"}]}
        assert docker_cli.calls[-1][1:] == ["buildx", "ls", "--format", "json"]

        docker_cli.responses.append(
            FakeProcess(stdout='{"name": "a"}\n{"name": "b"}\n')
        )
        result = await client.call_tool("docker_buildx_list", {})
        assert result.structured_content == {"result": [{"name": "a"}, {"name": "b"}]}

        docker_cli.responses.append(FakeProcess(stdout=""))
        result = await client.call_tool("docker_buildx_list", {})
        assert result.structured_content == {"result": []}

        docker_cli.responses.append(
            FakeProcess(stdout="", stderr="boom\n", returncode=1)
        )
        result = await client.call_tool("docker_buildx_list", {})
        assert result.is_error
        assert "boom" in result.content[0].text


@pytest.mark.anyio
async def test_buildx_reports_missing_docker_cli(server, monkeypatch):
    monkeypatch.setattr(server_module.shutil, "which", lambda _name: None)
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_buildx_list", {})
    assert result.is_error
    assert "docker CLI not found" in result.content[0].text


@pytest.mark.anyio
async def test_buildx_history_calls_buildx_with_optional_builder(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(FakeProcess(stdout='[{"name": "build-1"}]'))
        result = await client.call_tool("docker_buildx_history", {})
        assert result.structured_content == {"result": [{"name": "build-1"}]}
        assert docker_cli.calls[-1][1:] == [
            "buildx",
            "history",
            "ls",
            "--format",
            "json",
        ]

        docker_cli.responses.append(FakeProcess(stdout=""))
        result = await client.call_tool("docker_buildx_history", {"builder": "sbx"})
        assert result.structured_content == {"result": []}
        assert docker_cli.calls[-1][1:] == [
            "buildx",
            "history",
            "ls",
            "--format",
            "json",
            "--builder",
            "sbx",
        ]


@pytest.mark.anyio
async def test_buildx_logs_returns_text_and_passes_options(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(FakeProcess(stdout="step 1\nstep 2\n"))
        result = await client.call_tool("docker_buildx_logs", {"ref": "abc"})
        assert result.content[0].text == "step 1\nstep 2\n"
        assert docker_cli.calls[-1][1:] == [
            "buildx",
            "history",
            "logs",
            "abc",
            "--progress",
            "plain",
        ]

        docker_cli.responses.append(FakeProcess(stdout="trace\n"))
        result = await client.call_tool(
            "docker_buildx_logs",
            {"ref": "abc", "builder": "sbx", "progress": "rawjson"},
        )
        assert result.content[0].text == "trace\n"
        assert docker_cli.calls[-1][1:] == [
            "buildx",
            "history",
            "logs",
            "abc",
            "--builder",
            "sbx",
            "--progress",
            "rawjson",
        ]


@pytest.mark.anyio
async def test_buildx_logs_uses_build_id_from_full_ref(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(FakeProcess(stdout="step 1\n"))
        result = await client.call_tool(
            "docker_buildx_logs",
            {"ref": "sbx-opencode-v3/sbx-opencode-v30/qja8gbqjwyxk5kia5isg62w1p"},
        )
        assert result.content[0].text == "step 1\n"
        assert docker_cli.calls[-1][1:] == [
            "buildx",
            "history",
            "logs",
            "qja8gbqjwyxk5kia5isg62w1p",
            "--progress",
            "plain",
        ]


@pytest.mark.anyio
async def test_buildx_logs_returns_stderr_output(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(FakeProcess(stdout="", stderr="step 1\nstep 2\n"))
        result = await client.call_tool("docker_buildx_logs", {"ref": "abc"})
        assert result.content[0].text == "step 1\nstep 2\n"
        assert docker_cli.kwargs[-1]["stdout"] is subprocess.PIPE
        assert docker_cli.kwargs[-1]["stderr"] is subprocess.STDOUT


@pytest.mark.anyio
async def test_buildx_logs_reports_unknown_ref(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(
            FakeProcess(stdout="", stderr="no record found\n", returncode=1)
        )
        result = await client.call_tool("docker_buildx_logs", {"ref": "unknown"})
        assert result.is_error
        assert "no record found" in result.content[0].text


@pytest.mark.anyio
async def test_buildx_logs_rejects_tty_progress(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_buildx_logs", {"ref": "abc", "progress": "tty"}
        )
    assert result.is_error
    message = result.content[0].text
    assert "plain" in message
    assert "rawjson" in message
    assert docker_cli.calls == []


@pytest.mark.anyio
async def test_buildx_du_reports_each_builder(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(
            FakeProcess(
                stdout='[{"Name": "default", "Current": true}, '
                '{"Name": "sbx", "Current": false}]'
            )
        )
        docker_cli.responses.append(
            FakeProcess(
                stdout="Shared:\t\t8.3kB\nPrivate:\t20.48kB\n"
                "Reclaimable:\t28.78kB\nTotal:\t\t28.78kB\n"
            )
        )
        docker_cli.responses.append(
            FakeProcess(stdout="Reclaimable:\t1kB\nTotal:\t1kB\n")
        )
        result = await client.call_tool("docker_buildx_du", {})
        assert result.structured_content == {
            "result": [
                {
                    "builder": "default",
                    "current": True,
                    "shared": "8.3kB",
                    "private": "20.48kB",
                    "reclaimable": "28.78kB",
                    "total": "28.78kB",
                },
                {
                    "builder": "sbx",
                    "current": False,
                    "shared": None,
                    "private": None,
                    "reclaimable": "1kB",
                    "total": "1kB",
                },
            ]
        }
        assert docker_cli.calls[0][1:] == ["buildx", "ls", "--format", "json"]
        assert docker_cli.calls[1][1:] == ["buildx", "du", "--builder", "default"]
        assert docker_cli.calls[2][1:] == ["buildx", "du", "--builder", "sbx"]


@pytest.mark.anyio
async def test_buildx_du_supports_single_builder_and_verbose(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(FakeProcess(stdout="Total:\t5kB\n"))
        docker_cli.responses.append(FakeProcess(stdout='{"ID": "a", "Size": "5kB"}\n'))
        result = await client.call_tool(
            "docker_buildx_du", {"builder": "sbx", "verbose": True}
        )
        assert result.structured_content == {
            "result": [
                {
                    "builder": "sbx",
                    "current": None,
                    "shared": None,
                    "private": None,
                    "reclaimable": None,
                    "total": "5kB",
                    "records": [{"ID": "a", "Size": "5kB"}],
                }
            ]
        }
        assert docker_cli.calls[0][1:] == ["buildx", "du", "--builder", "sbx"]
        assert docker_cli.calls[1][1:] == [
            "buildx",
            "du",
            "--builder",
            "sbx",
            "--format",
            "json",
        ]


@pytest.mark.anyio
async def test_buildx_du_keeps_other_builders_when_one_fails(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(
            FakeProcess(stdout='[{"Name": "broken"}, {"Name": "ok"}]')
        )
        docker_cli.responses.append(
            FakeProcess(stdout="", stderr="builder not found\n", returncode=1)
        )
        docker_cli.responses.append(FakeProcess(stdout="Total:\t2kB\n"))
        result = await client.call_tool("docker_buildx_du", {})
        assert not result.is_error
        assert result.structured_content == {
            "result": [
                {"builder": "broken", "current": None, "error": "builder not found"},
                {
                    "builder": "ok",
                    "current": None,
                    "shared": None,
                    "private": None,
                    "reclaimable": None,
                    "total": "2kB",
                },
            ]
        }


@pytest.mark.anyio
async def test_system_df_reports_missing_docker_cli(server, monkeypatch):
    monkeypatch.setattr(server_module.shutil, "which", lambda _name: None)
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_system_df", {})
    assert result.is_error
    assert "docker CLI not found" in result.content[0].text


@pytest.mark.anyio
async def test_system_df_returns_summary_and_optional_detail(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(
            FakeProcess(
                stdout='{"Type": "Images", "Size": "0B"}\n'
                '{"Type": "Containers", "Size": "0B"}\n'
            )
        )
        result = await client.call_tool("docker_system_df", {})
        assert result.structured_content == {
            "summary": [
                {"Type": "Images", "Size": "0B"},
                {"Type": "Containers", "Size": "0B"},
            ]
        }
        assert docker_cli.calls[-1][1:] == ["system", "df", "--format", "json"]

        docker_cli.responses.append(
            FakeProcess(stdout='{"Type": "Images", "Size": "0B"}\n')
        )
        docker_cli.responses.append(
            FakeProcess(
                stdout='{"Images": [], "Containers": [], '
                '"Volumes": [], "BuildCache": []}'
            )
        )
        result = await client.call_tool("docker_system_df", {"verbose": True})
        assert result.structured_content == {
            "summary": [{"Type": "Images", "Size": "0B"}],
            "detail": {
                "Images": [],
                "Containers": [],
                "Volumes": [],
                "BuildCache": [],
            },
        }
        assert docker_cli.calls[-1][1:] == [
            "system",
            "df",
            "-v",
            "--format",
            "json",
        ]


@pytest.mark.anyio
async def test_container_prune_returns_deleted_and_reclaimed(server, docker_client):
    docker_client.containers.prune_payload = {
        "ContainersDeleted": ["c1", "c2"],
        "SpaceReclaimed": 42,
    }
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_container_prune", {})
    assert result.structured_content == {
        "deleted": ["c1", "c2"],
        "space_reclaimed": 42,
    }
    assert docker_client.call("containers.prune") == {}


@pytest.mark.anyio
async def test_image_prune_returns_deleted_entries(server, docker_client):
    docker_client.images.prune_payload = {
        "ImagesDeleted": [{"Deleted": "sha256:abc"}],
        "SpaceReclaimed": 7,
    }
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_image_prune", {})
    assert result.structured_content == {
        "deleted": [{"Deleted": "sha256:abc"}],
        "space_reclaimed": 7,
    }
    assert docker_client.call("images.prune") == {"filters": {"dangling": True}}


@pytest.mark.anyio
async def test_volume_prune_returns_deleted_volumes(server, docker_client):
    docker_client.volumes.prune_payload = {
        "VolumesDeleted": ["v1"],
        "SpaceReclaimed": 3,
    }
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_volume_prune", {})
    assert result.structured_content == {"deleted": ["v1"], "space_reclaimed": 3}
    assert docker_client.call("volumes.prune") == {}


@pytest.mark.anyio
async def test_system_prune_aggregates_without_volumes_by_default(
    server, docker_client
):
    docker_client.containers.prune_payload = {
        "ContainersDeleted": ["c1"],
        "SpaceReclaimed": 10,
    }
    docker_client.networks.prune_payload = {"NetworksDeleted": ["n1"]}
    docker_client.images.prune_payload = {
        "ImagesDeleted": [{"Deleted": "sha256:abc"}],
        "SpaceReclaimed": 5,
    }
    docker_client.api.prune_builds_payload = {
        "CachesDeleted": ["cache1"],
        "SpaceReclaimed": 3,
    }
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_system_prune", {})
    assert result.structured_content == {
        "space_reclaimed": 18,
        "containers": {"deleted": ["c1"], "space_reclaimed": 10},
        "networks": {"deleted": ["n1"], "space_reclaimed": 0},
        "images": {"deleted": [{"Deleted": "sha256:abc"}], "space_reclaimed": 5},
        "build_cache": {"deleted": ["cache1"], "space_reclaimed": 3},
    }
    assert docker_client.call("images.prune") == {"filters": {"dangling": False}}
    assert docker_client.call("api.prune_builds") == {"all": True}
    assert all(key != "volumes.prune" for key, _ in docker_client.calls)


@pytest.mark.anyio
async def test_system_prune_opt_in_volumes_and_dangling_only(server, docker_client):
    docker_client.volumes.prune_payload = {
        "VolumesDeleted": ["v1"],
        "SpaceReclaimed": 2,
    }
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_system_prune", {"all": False, "volumes": True}
        )
    assert result.structured_content["volumes"] == {
        "deleted": ["v1"],
        "space_reclaimed": 2,
    }
    assert result.structured_content["space_reclaimed"] == 2
    assert docker_client.call("images.prune") == {"filters": {"dangling": True}}
    assert docker_client.call("api.prune_builds") == {"all": False}


@pytest.mark.anyio
async def test_buildx_prune_reports_reclaimed_space_and_deleted_ids(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(
            FakeProcess(stdout='[{"Name": "default", "Current": true}]')
        )
        docker_cli.responses.append(
            FakeProcess(
                stdout="ID              RECLAIMABLE   SIZE    LAST ACCESSED\n"
                "abc123          true          1.2kB   2 days ago\n"
                "Total:   1.2kB\n"
            )
        )
        result = await client.call_tool("docker_buildx_prune", {})
        assert not result.is_error
        assert result.structured_content == {
            "result": [
                {
                    "builder": "default",
                    "current": True,
                    "reclaimed": "1.2kB",
                    "deleted": ["abc123"],
                }
            ]
        }
        assert docker_cli.calls[0][1:] == ["buildx", "ls", "--format", "json"]
        assert docker_cli.calls[1][1:] == [
            "buildx",
            "prune",
            "--builder",
            "default",
            "--force",
            "--all",
        ]


@pytest.mark.anyio
async def test_buildx_prune_supports_single_builder_without_all(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(FakeProcess(stdout="Total:   0B\n"))
        result = await client.call_tool(
            "docker_buildx_prune", {"builder": "sbx", "all": False}
        )
        assert result.structured_content == {
            "result": [
                {
                    "builder": "sbx",
                    "current": None,
                    "reclaimed": "0B",
                    "deleted": [],
                }
            ]
        }
        assert docker_cli.calls[0][1:] == [
            "buildx",
            "prune",
            "--builder",
            "sbx",
            "--force",
        ]


@pytest.mark.anyio
async def test_buildx_prune_keeps_other_builders_when_one_fails(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(
            FakeProcess(stdout='[{"Name": "broken"}, {"Name": "ok"}]')
        )
        docker_cli.responses.append(
            FakeProcess(stdout="", stderr="builder not found\n", returncode=1)
        )
        docker_cli.responses.append(
            FakeProcess(
                stdout="ID       RECLAIMABLE   SIZE   LAST ACCESSED\n"
                "deadbeef true          2kB    1 day ago\n"
                "Total:   2kB\n"
            )
        )
        result = await client.call_tool("docker_buildx_prune", {})
        assert not result.is_error
        assert result.structured_content == {
            "result": [
                {"builder": "broken", "current": None, "error": "builder not found"},
                {
                    "builder": "ok",
                    "current": None,
                    "reclaimed": "2kB",
                    "deleted": ["deadbeef"],
                },
            ]
        }


@pytest.mark.anyio
async def test_buildx_build_passes_flags_and_returns_build_ref(server, docker_cli):
    docker_cli.metadata = {"buildx.build.ref": "sbx/sbx0/build-1"}
    docker_cli.responses.append(FakeProcess(stdout="step 1\nstep 2\n"))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_buildx_build",
            {
                "context": ".",
                "dockerfile": "Dockerfile",
                "tags": ["app:1", "app:latest"],
                "target": "prod",
                "build_args": {"A": "B"},
                "builder": "sbx",
                "cache_from": ["type=local,src=/tmp/c"],
                "cache_to": ["type=local,dest=/tmp/c2"],
                "platform": ["linux/amd64"],
                "no_cache": True,
                "timeout_seconds": 5,
            },
        )
    assert not result.is_error
    assert result.structured_content == {
        "ref": "sbx/sbx0/build-1",
        "output": "step 1\nstep 2\n",
        "truncated": False,
        "bytes": 14,
    }
    command = docker_cli.calls[-1][1:]
    metadata_index = command.index("--metadata-file")
    assert command[:metadata_index] == [
        "buildx",
        "build",
        "--progress",
        "plain",
        "--file",
        "Dockerfile",
        "--tag",
        "app:1",
        "--tag",
        "app:latest",
        "--target",
        "prod",
        "--build-arg",
        "A=B",
        "--builder",
        "sbx",
        "--cache-from",
        "type=local,src=/tmp/c",
        "--cache-to",
        "type=local,dest=/tmp/c2",
        "--platform",
        "linux/amd64",
        "--no-cache",
    ]
    assert command[metadata_index + 1].endswith("metadata.json")
    assert command[-1] == "."
    assert docker_cli.kwargs[-1]["timeout"] == 5


@pytest.mark.anyio
async def test_buildx_build_returns_log_tail_on_failure(server, docker_cli):
    docker_cli.responses.append(
        FakeProcess(stdout="", stderr="ERROR: failed to solve\nstep 1\n", returncode=1)
    )
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_buildx_build", {"context": "."})
    assert result.is_error
    message = result.content[0].text
    assert "exited with code 1" in message
    assert "ERROR: failed to solve" in message
    assert "step 1" in message


@pytest.mark.anyio
async def test_buildx_build_reports_timeout_with_log_tail(server, docker_cli):
    docker_cli.responses.append(
        subprocess.TimeoutExpired(["docker"], 2, output=b"step 1\nstep 2\n")
    )
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_buildx_build", {"context": ".", "timeout_seconds": 2}
        )
    assert result.is_error
    message = result.content[0].text
    assert "timed out after 2s" in message
    assert "step 2" in message


@pytest.mark.anyio
async def test_buildx_build_rejects_push_and_load_together(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_buildx_build",
            {"context": ".", "tags": ["app:1"], "push": True, "load": True},
        )
    assert result.is_error
    assert "mutually exclusive" in result.content[0].text
    assert docker_cli.calls == []


@pytest.mark.anyio
async def test_buildx_build_requires_tag_for_push(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_buildx_build", {"context": ".", "push": True}
        )
    assert result.is_error
    assert "requires at least one tag" in result.content[0].text
    assert docker_cli.calls == []


@pytest.mark.anyio
async def test_buildx_build_push_uses_push_flag(server, docker_cli):
    docker_cli.metadata = {"buildx.build.ref": "default/default/build-2"}
    docker_cli.responses.append(FakeProcess(stdout="pushed\n"))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_buildx_build",
            {"context": ".", "tags": ["registry/app:1"], "push": True},
        )
    assert not result.is_error
    assert "--push" in docker_cli.calls[-1]
    assert "--load" not in docker_cli.calls[-1]


@pytest.mark.anyio
async def test_buildx_build_load_uses_load_flag(server, docker_cli):
    docker_cli.metadata = {"buildx.build.ref": "default/default/build-load"}
    docker_cli.responses.append(FakeProcess(stdout="loaded\n"))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_buildx_build",
            {"context": ".", "tags": ["app:local"], "load": True},
        )
    assert not result.is_error
    assert "--load" in docker_cli.calls[-1]
    assert "--push" not in docker_cli.calls[-1]


@pytest.mark.anyio
async def test_buildx_build_reports_missing_docker_cli(server, monkeypatch):
    monkeypatch.setattr(server_module.shutil, "which", lambda _name: None)
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_buildx_build", {"context": "."})
    assert result.is_error
    assert "docker CLI not found" in result.content[0].text


@pytest.mark.anyio
async def test_buildx_build_truncates_output(server, docker_cli):
    docker_cli.metadata = {"buildx.build.ref": "default/default/build-3"}
    docker_cli.responses.append(FakeProcess(stdout="a" * (20 * 1024 + 500)))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_buildx_build", {"context": "."})
    assert result.structured_content["bytes"] == 20 * 1024 + 500
    assert result.structured_content["truncated"] is True
    assert len(result.structured_content["output"]) == 20 * 1024


@pytest.mark.anyio
async def test_buildx_build_clamps_timeout(server, docker_cli):
    docker_cli.metadata = {"buildx.build.ref": "default/default/build-4"}
    docker_cli.responses.append(FakeProcess(stdout="ok\n"))
    docker_cli.responses.append(FakeProcess(stdout="ok\n"))
    async with Client(server, raise_exceptions=True) as client:
        await client.call_tool(
            "docker_buildx_build", {"context": ".", "timeout_seconds": 9999}
        )
        await client.call_tool(
            "docker_buildx_build", {"context": ".", "timeout_seconds": 0}
        )
    assert docker_cli.kwargs[-2]["timeout"] == 3600
    assert docker_cli.kwargs[-1]["timeout"] == 1


@pytest.mark.anyio
async def test_buildx_build_reports_missing_build_ref(server, docker_cli):
    docker_cli.metadata = {}
    docker_cli.responses.append(FakeProcess(stdout="ok\n"))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_buildx_build", {"context": "."})
    assert result.is_error
    assert "did not report a build reference" in result.content[0].text


@pytest.mark.anyio
async def test_image_inspect_redacts_env_and_image_history_returns_layers(
    server, docker_client
):
    class Image:
        attrs: ClassVar = {
            "Config": {"Env": ["SECRET=abc"]},
            "ContainerConfig": {"Env": ["TOKEN=x=y"]},
        }

        def history(self):
            return [{"Id": "layer-1", "CreatedBy": "COPY hello.txt"}]

    docker_client.images.get = lambda name: (
        docker_client.calls.append(("images.get", name)),
        Image(),
    )[1]

    async with Client(server, raise_exceptions=True) as client:
        inspect = await client.call_tool("docker_image_inspect", {"image": "alpine"})
        assert inspect.structured_content == {
            "Config": {"Env": ["SECRET=<redacted>"]},
            "ContainerConfig": {"Env": ["TOKEN=<redacted>"]},
        }
        history = await client.call_tool("docker_image_history", {"image": "alpine"})
        assert history.structured_content == {
            "result": [{"Id": "layer-1", "CreatedBy": "COPY hello.txt"}]
        }
        assert docker_client.call("images.get") == "alpine"


@pytest.mark.anyio
async def test_buildx_inspect_returns_text_and_optional_builder(server, docker_cli):
    async with Client(server, raise_exceptions=True) as client:
        docker_cli.responses.append(
            FakeProcess(stdout="Name:   default\nDriver: docker\n")
        )
        result = await client.call_tool("docker_buildx_inspect", {})
        assert result.content[0].text == "Name:   default\nDriver: docker\n"
        assert docker_cli.calls[-1][1:] == ["buildx", "inspect"]

        docker_cli.responses.append(
            FakeProcess(stdout="Name:   sbx\nDriver: docker-container\n")
        )
        result = await client.call_tool("docker_buildx_inspect", {"builder": "sbx"})
        assert result.content[0].text == "Name:   sbx\nDriver: docker-container\n"
        assert docker_cli.calls[-1][1:] == [
            "buildx",
            "inspect",
            "--builder",
            "sbx",
        ]


@pytest.mark.anyio
async def test_container_inspect_redacts_env(server, docker_client):
    class Container:
        attrs: ClassVar = {
            "Config": {"Env": ["SECRET=abc"]},
            "ContainerConfig": {"Env": ["TOKEN=x=y"]},
            "State": {"Running": True},
        }

    docker_client.containers.get = lambda name: (
        docker_client.calls.append(("containers.get", name)),
        Container(),
    )[1]

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_container_inspect", {"container_id": "web"}
        )
        assert result.structured_content == {
            "Config": {"Env": ["SECRET=<redacted>"]},
            "ContainerConfig": {"Env": ["TOKEN=<redacted>"]},
            "State": {"Running": True},
        }
        assert docker_client.call("containers.get") == "web"


@pytest.mark.anyio
async def test_container_processes_calls_docker_top(server, docker_client):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_container_processes", {"container_id": "web"}
        )
        assert result.structured_content == {
            "Titles": ["PID", "CMD"],
            "Processes": [["1", "nginx"]],
        }
        assert docker_client.calls[-2:] == [
            ("containers.get", "web"),
            ("object.top", None),
        ]


@pytest.mark.anyio
async def test_container_stats_tool_returns_one_shot_snapshot(server, docker_client):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_container_stats", {"container_id": "web"}
        )
        assert result.structured_content == {"cpu": 1}
        assert docker_client.calls[-2:] == [
            ("containers.get", "web"),
            ("object.stats", {"stream": False}),
        ]


@pytest.mark.anyio
async def test_container_exec_runs_argv_and_returns_output(server, docker_client):
    docker_client.api.exec_output = [b"ho", b"la\n"]
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_container_exec",
            {
                "container_id": "web",
                "command": ["ls", "-l"],
                "workdir": "/tmp",
                "env": {"A": "B"},
                "timeout_seconds": 5,
            },
        )
    assert result.structured_content == {
        "exit_code": 0,
        "output": "hola\n",
        "truncated": False,
        "bytes": 5,
    }
    assert docker_client.call("api.exec_create") == (
        "object-id",
        ["ls", "-l"],
        {
            "workdir": "/tmp",
            "environment": {"A": "B"},
            "tty": False,
            "stdin": False,
        },
    )
    assert docker_client.call("api.exec_start") == ("exec-1", {"stream": True})
    assert docker_client.call("api.exec_inspect") == "exec-1"


@pytest.mark.anyio
async def test_container_exec_returns_nonzero_exit_code(server, docker_client):
    docker_client.api.exec_output = [b"boom\n"]
    docker_client.api.exec_exit_code = 2
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_container_exec",
            {"container_id": "web", "command": ["false"]},
        )
    assert not result.is_error
    assert result.structured_content == {
        "exit_code": 2,
        "output": "boom\n",
        "truncated": False,
        "bytes": 5,
    }


@pytest.mark.anyio
async def test_container_exec_truncates_output_to_last_20_kib(server, docker_client):
    payload = b"x" * 1000 + b"y" * (20 * 1024 + 100)
    docker_client.api.exec_output = [payload]
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_container_exec",
            {"container_id": "web", "command": ["cat", "big"]},
        )
    assert result.structured_content["bytes"] == len(payload)
    assert result.structured_content["truncated"] is True
    assert len(result.structured_content["output"]) == 20 * 1024
    assert result.structured_content["output"].startswith("y")


@pytest.mark.anyio
async def test_container_exec_times_out(server, docker_client):
    release = threading.Event()

    class BlockingStream:
        def __iter__(self):
            return self

        def __next__(self):
            release.wait()
            raise StopIteration

    docker_client.api.exec_stream = BlockingStream()
    try:
        async with Client(server, raise_exceptions=True) as client:
            result = await client.call_tool(
                "docker_container_exec",
                {
                    "container_id": "web",
                    "command": ["sleep", "60"],
                    "timeout_seconds": 1,
                },
            )
    finally:
        release.set()
    assert result.is_error
    assert "timed out" in result.content[0].text


@pytest.mark.anyio
async def test_container_exec_reports_exec_failures(server, docker_client):
    def fail(exec_id, **kwargs):
        raise docker.errors.APIError("exec failed")

    docker_client.api.exec_start = fail
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_container_exec",
            {"container_id": "web", "command": ["ls"]},
        )
    assert result.is_error
    assert "exec failed" in result.content[0].text


@pytest.mark.anyio
async def test_version_and_curated_system_info(server, docker_client):
    async with Client(server, raise_exceptions=True) as client:
        version = await client.call_tool("docker_version", {})
        assert version.structured_content == {
            "Version": "29.9.3",
            "ApiVersion": "1.52",
        }

        info = await client.call_tool("docker_system_info", {})
        assert info.structured_content == {
            "ServerVersion": "29.9.3",
            "Driver": "overlay2",
            "DriverStatus": [["Backing Filesystem", "extfs"]],
            "NCPU": 8,
            "MemTotal": 16_000_000_000,
            "Containers": 3,
            "Images": 5,
        }
        assert "HttpProxy" not in info.structured_content
        assert "RegistryConfig" not in info.structured_content


@pytest.mark.anyio
async def test_docker_status_reports_reachable_daemon(server, docker_client):
    docker_client.api.payload = {"Version": "29.9.3", "ApiVersion": "1.52"}

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_status", {})

    payload = result.structured_content
    assert result.is_error is False
    assert payload["status"] == "ok"
    assert payload["server"] == {
        "name": "docker-server",
        "version": server_module.__version__,
    }
    assert payload["docker"]["reachable"] is True
    assert payload["docker"]["version"] == "29.9.3"
    assert payload["docker"]["api_version"] == "1.52"
    assert isinstance(payload["docker"]["latency_ms"], int)
    assert payload["checked_at"].endswith("Z")
    assert docker_client.api.timeouts == [2.0]


@pytest.mark.anyio
async def test_docker_status_reports_degraded_without_leaking_host_details(
    server, docker_client
):
    docker_client.api.error = OSError(
        "Cannot connect to the Docker daemon at unix:///var/run/docker.sock"
    )

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_status", {})

    payload = result.structured_content
    assert result.is_error is False
    assert payload["status"] == "degraded"
    assert payload["docker"]["reachable"] is False
    assert "docker.sock" not in payload["docker"]["error"]
    assert "Cannot connect" in payload["docker"]["error"]


@pytest.mark.anyio
async def test_docker_status_reports_degraded_on_http_error(server, docker_client):
    docker_client.api.status_code = 500

    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_status", {})

    assert result.structured_content["status"] == "degraded"
    assert "HTTP 500" in result.structured_content["docker"]["error"]


@pytest.mark.anyio
async def test_tools_have_flat_schemas_and_container_call_semantics(
    server, docker_client
):
    async with Client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
        assert len(tools.tools) == 44
        buildx_list_tool = next(
            tool for tool in tools.tools if tool.name == "docker_buildx_list"
        )
        assert buildx_list_tool.annotations.read_only_hint
        assert buildx_list_tool.annotations.idempotent_hint
        assert buildx_list_tool.annotations.open_world_hint is False
        buildx_du_tool = next(
            tool for tool in tools.tools if tool.name == "docker_buildx_du"
        )
        assert buildx_du_tool.annotations.read_only_hint
        assert buildx_du_tool.annotations.idempotent_hint
        assert buildx_du_tool.annotations.open_world_hint is False
        system_df_tool = next(
            tool for tool in tools.tools if tool.name == "docker_system_df"
        )
        assert system_df_tool.annotations.read_only_hint
        assert system_df_tool.annotations.idempotent_hint
        assert system_df_tool.annotations.open_world_hint is False
        for name in (
            "docker_container_prune",
            "docker_image_prune",
            "docker_volume_prune",
            "docker_system_prune",
            "docker_buildx_prune",
            "docker_buildx_build",
        ):
            prune_tool = next(tool for tool in tools.tools if tool.name == name)
            assert prune_tool.annotations.destructive_hint
            assert not prune_tool.annotations.read_only_hint
            assert prune_tool.annotations.open_world_hint is False
        exec_tool = next(
            tool for tool in tools.tools if tool.name == "docker_container_exec"
        )
        assert not exec_tool.annotations.read_only_hint
        assert exec_tool.annotations.destructive_hint is False
        assert exec_tool.annotations.open_world_hint is False
        for name in ("docker_version", "docker_system_info", "docker_status"):
            tool = next(tool for tool in tools.tools if tool.name == name)
            assert tool.annotations.read_only_hint
            assert tool.annotations.idempotent_hint
            assert tool.annotations.open_world_hint is False
        for name in ("docker_container_inspect", "docker_container_processes"):
            tool = next(tool for tool in tools.tools if tool.name == name)
            assert tool.annotations.read_only_hint
            assert tool.annotations.idempotent_hint
            assert tool.annotations.open_world_hint is False
        stats_annotations = next(
            tool for tool in tools.tools if tool.name == "docker_container_stats"
        ).annotations
        assert stats_annotations.read_only_hint
        assert stats_annotations.idempotent_hint is False
        assert stats_annotations.open_world_hint is False
        buildx_inspect_tool = next(
            tool for tool in tools.tools if tool.name == "docker_buildx_inspect"
        )
        assert buildx_inspect_tool.annotations.read_only_hint
        assert buildx_inspect_tool.annotations.idempotent_hint
        assert buildx_inspect_tool.annotations.open_world_hint is False
        for name in ("docker_image_inspect", "docker_image_history"):
            tool = next(tool for tool in tools.tools if tool.name == name)
            assert tool.annotations.read_only_hint
            assert tool.annotations.idempotent_hint
            assert tool.annotations.open_world_hint is False
        create = next(
            tool for tool in tools.tools if tool.name == "docker_create_container"
        )
        assert create.input_schema["required"] == ["image"]
        assert "ctx" not in create.input_schema["properties"]
        assert "input" not in create.input_schema["properties"]
        assert (
            create.input_schema["properties"]["image"]["description"]
            == "Docker image name"
        )
        annotations = next(
            tool for tool in tools.tools if tool.name == "docker_list_containers"
        ).annotations
        assert annotations.read_only_hint
        assert annotations.idempotent_hint
        assert annotations.open_world_hint is False
        remove = next(
            tool for tool in tools.tools if tool.name == "docker_remove_container"
        )
        assert remove.annotations.destructive_hint
        assert remove.annotations.open_world_hint is False

        await client.call_tool("docker_list_containers", {})
        assert docker_client.call("containers.list") == {"all": False, "filters": None}
        docker_client.api.payload = [{"Id": "id-1"}]
        await client.call_tool(
            "docker_list_containers", {"all": True, "filters": {"label": ["a=b"]}}
        )
        assert docker_client.call("api.get") == (
            "http://docker/containers/json",
            {"all": 1, "filters": '{"label": {"a=b": true}}'},
        )
        assert ("containers.get", "id-1") in docker_client.calls
        await client.call_tool(
            "docker_create_container",
            {"image": "alpine", "name": "new", "environment": {"X": "1"}},
        )
        assert docker_client.call("containers.create")["image"] == "alpine"
        assert docker_client.call("containers.create")["environment"] == {"X": "1"}
        await client.call_tool(
            "docker_create_container",
            {"image": "alpine", "ports": {"80/tcp": ["127.0.0.1", 8080]}},
        )
        assert docker_client.call("containers.create")["ports"] == {
            "80/tcp": ("127.0.0.1", 8080)
        }
        attached = await client.call_tool(
            "docker_run_container", {"image": "alpine", "detach": False}
        )
        assert docker_client.call("containers.run")["detach"] is False
        assert attached.structured_content == {
            "mode": "attached",
            "output": "attached\ufffd\n",
            "truncated": False,
            "bytes": 10,
        }
        await client.call_tool(
            "docker_recreate_container", {"image": "alpine", "name": "old"}
        )
        assert docker_client.call("containers.get") == "old"
        assert [name for name, _ in docker_client.calls[-4:]] == [
            "containers.get",
            "object.stop",
            "object.remove",
            "containers.run",
        ]
        recreated = docker_client.call("containers.run")
        assert "container_id" not in recreated
        assert "resolved_container_id" not in recreated
        await client.call_tool("docker_start_container", {"container_id": "x"})
        assert docker_client.calls[-2:] == [
            ("containers.get", "x"),
            ("object.start", None),
        ]
        await client.call_tool("docker_fetch_container_logs", {"container_id": "x"})
        assert docker_client.call("object.logs") == {"tail": 100}
        await client.call_tool(
            "docker_fetch_container_logs", {"container_id": "x", "tail": "all"}
        )
        assert docker_client.call("object.logs") == {"tail": "all"}
        await client.call_tool("docker_stop_container", {"container_id": "x"})
        assert docker_client.calls[-2:] == [
            ("containers.get", "x"),
            ("object.stop", None),
        ]
        await client.call_tool(
            "docker_remove_container", {"container_id": "x", "force": True}
        )
        assert docker_client.call("object.remove") == {"force": True}


@pytest.mark.anyio
async def test_list_containers_filtered_uses_engine_map_form_and_resolves_ids(
    server, docker_client
):
    docker_client.api.payload = [{"Id": "a"}, {"Id": "b"}]
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_list_containers",
            {
                "all": True,
                "filters": {"label": ["io.kubernetes.pod.namespace=kube-system"]},
            },
        )

    assert docker_client.call("api.get") == (
        "http://docker/containers/json",
        {
            "all": 1,
            "filters": '{"label": {"io.kubernetes.pod.namespace=kube-system": true}}',
        },
    )
    assert [
        value for name, value in docker_client.calls if name == "containers.get"
    ] == ["a", "b"]
    assert result.structured_content == {
        "result": [{"id": "object-id"}, {"id": "object-id"}]
    }


@pytest.mark.anyio
async def test_list_containers_with_empty_filters_uses_plain_list(
    server, docker_client
):
    async with Client(server, raise_exceptions=True) as client:
        await client.call_tool("docker_list_containers", {"all": True, "filters": {}})

    assert docker_client.call("containers.list") == {"all": True, "filters": None}
    assert all(name != "api.get" for name, _ in docker_client.calls)


@pytest.mark.anyio
async def test_image_network_and_volume_call_semantics(server, docker_client):
    async with Client(server, raise_exceptions=True) as client:
        await client.call_tool("docker_list_images", {})
        assert docker_client.call("images.list") == {
            "name": None,
            "all": False,
            "filters": None,
        }
        await client.call_tool(
            "docker_list_images",
            {"name": "alpine", "all": True, "filters": {"dangling": True}},
        )
        assert docker_client.call("images.list") == {
            "name": "alpine",
            "all": True,
            "filters": {"dangling": True},
        }
        await client.call_tool(
            "docker_pull_image", {"repository": "alpine", "tag": "3.20"}
        )
        assert docker_client.call("images.pull") == ("alpine", {"tag": "3.20"})
        await client.call_tool("docker_push_image", {"repository": "alpine"})
        assert docker_client.call("images.push") == ("alpine", {"tag": "latest"})
        build = await client.call_tool(
            "docker_build_image",
            {"path": ".", "tag": "test", "dockerfile": "Dockerfile.test"},
        )
        assert build.structured_content["logs"] == [{"stream": "built"}]
        assert docker_client.call("images.build") == {
            "path": ".",
            "tag": "test",
            "dockerfile": "Dockerfile.test",
            "rm": True,
            "forcerm": True,
        }
        await client.call_tool("docker_remove_image", {"image": "test", "force": True})
        assert docker_client.call("images.remove") == {"image": "test", "force": True}
        await client.call_tool("docker_list_networks", {"filters": {"label": ["x=y"]}})
        assert docker_client.call("networks.list") == {"filters": {"label": ["x=y"]}}
        await client.call_tool("docker_list_networks", {"filters": {}})
        assert docker_client.call("networks.list") == {"filters": None}
        await client.call_tool("docker_create_network", {"name": "n", "internal": True})
        assert docker_client.call("networks.create") == {
            "name": "n",
            "driver": "bridge",
            "internal": True,
            "labels": None,
        }
        await client.call_tool("docker_remove_network", {"network_id": "n"})
        assert docker_client.calls[-2:] == [
            ("networks.get", "n"),
            ("object.remove", {}),
        ]
        await client.call_tool("docker_list_volumes", {})
        assert docker_client.call("volumes.list") == {}
        await client.call_tool("docker_create_volume", {"name": "v"})
        assert docker_client.call("volumes.create") == {
            "name": "v",
            "driver": "local",
            "labels": None,
        }
        await client.call_tool(
            "docker_remove_volume", {"volume_name": "v", "force": True}
        )
        assert docker_client.call("object.remove") == {"force": True}


@pytest.mark.anyio
async def test_list_tools_return_one_json_array_block(server, docker_client):
    objects = [Object(docker_client.calls), Object(docker_client.calls)]
    docker_client.volumes.list = lambda **_kwargs: objects
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_list_volumes", {})

    assert len(result.content) == 1
    payload = [{"id": "object-id"}, {"id": "object-id"}]
    assert json.loads(result.content[0].text) == payload
    assert result.structured_content == {"result": payload}


@pytest.mark.anyio
async def test_list_tools_return_empty_array_block(server, docker_client):
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_list_volumes", {})

    assert len(result.content) == 1
    assert json.loads(result.content[0].text) == []
    assert result.structured_content == {"result": []}


@pytest.mark.anyio
async def test_container_logs_replace_undecodable_bytes(
    server, docker_client, monkeypatch
):
    monkeypatch.setattr(Object, "logs_payload", b"line\x90\n")
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_fetch_container_logs", {"container_id": "x"}
        )
        logs = (await client.read_resource("docker://containers/x/logs")).contents[0]
    assert result.structured_content == {
        "logs": ["line\ufffd", ""],
        "truncated": False,
        "bytes": len(b"line\x90\n"),
    }
    assert logs.text == "line\ufffd\n"


@pytest.mark.anyio
async def test_resources_prompt_validation_errors_and_lifetime(server, docker_client):
    async with Client(server, raise_exceptions=True) as client:
        templates = await client.list_resource_templates()
        assert {template.uri_template for template in templates.resource_templates} == {
            "docker://containers/{container_id}/logs",
            "docker://containers/{container_id}/stats",
        }
        logs = (await client.read_resource("docker://containers/x/logs")).contents[0]
        stats = (await client.read_resource("docker://containers/x/stats")).contents[0]
        assert (logs.mime_type, logs.text) == ("text/plain", "line\n")
        assert stats.mime_type == "application/json"
        assert '"cpu": 1' in stats.text
        before = len(docker_client.calls)
        assert (await client.call_tool("docker_create_container", {})).is_error
        assert len(docker_client.calls) == before
        prompts = await client.list_prompts()
        assert all(argument.required for argument in prompts.prompts[0].arguments)
        with pytest.raises(MCPError, match="Missing required arguments"):
            await client.get_prompt("docker_compose", {"name": "p"})
        prompt = await client.get_prompt(
            "docker_compose", {"name": "p", "containers": "nginx"}
        )
        assert "mcp-server-docker.project=p" in prompt.messages[0].content.text
        assert "<BEGIN FORMAT>" in prompt.messages[0].content.text
    assert docker_client.closed


@pytest.mark.anyio
async def test_docker_exception_is_a_model_visible_tool_error(server, docker_client):
    def fail(**_kwargs):
        raise docker.errors.APIError("daemon unavailable")

    docker_client.containers.list = fail
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_list_containers", {})
    assert result.is_error
    assert "daemon unavailable" in result.content[0].text


@pytest.mark.anyio
async def test_internally_created_client_is_closed(monkeypatch):
    client = Docker()
    monkeypatch.setattr(server_module.docker, "from_env", lambda: client)
    async with Client(app, raise_exceptions=True) as mcp_client:
        await mcp_client.list_tools()
    assert client.closed


@pytest.mark.anyio
async def test_production_stdio_command_lists_all_tools():
    params = StdioServerParameters(command="uv", args=["run", "mcp-server-docker"])
    async with Client(stdio_client(params), raise_exceptions=True) as client:
        tools = await client.list_tools()
    assert len(tools.tools) == 44
    assert "docker_list_containers" in {tool.name for tool in tools.tools}
    assert "docker_container_stats" in {tool.name for tool in tools.tools}


@pytest.mark.anyio
async def test_production_stdio_read_only_env_exposes_only_read_only_tools():
    params = StdioServerParameters(
        command="uv",
        args=["run", "mcp-server-docker"],
        env={"MCP_SERVER_DOCKER_READ_ONLY": "1"},
    )
    async with Client(stdio_client(params), raise_exceptions=True) as client:
        tools = await client.list_tools()
        templates = await client.list_resource_templates()
        prompts = await client.list_prompts()
        blocked = await client.call_tool("docker_create_container", {"image": "alpine"})

    names = {tool.name for tool in tools.tools}
    assert len(names) == 23
    assert all(tool.annotations.read_only_hint for tool in tools.tools)
    assert "docker_create_container" not in names
    assert {
        "docker_network_inspect",
        "docker_volume_inspect",
        "docker_container_health",
        "docker_events_list",
    } <= names
    assert "docker_buildx_du" in names
    assert "docker_container_stats" in names
    assert {
        "docker_container_prune",
        "docker_image_prune",
        "docker_volume_prune",
        "docker_system_prune",
        "docker_buildx_prune",
        "docker_buildx_build",
        "docker_container_exec",
    }.isdisjoint(names)
    assert {template.uri_template for template in templates.resource_templates} == {
        "docker://containers/{container_id}/logs",
        "docker://containers/{container_id}/stats",
    }
    assert prompts.prompts
    assert blocked.is_error
    assert "Unknown tool" in blocked.content[0].text


@pytest.mark.anyio
async def test_production_stdio_read_only_cli_flag():
    params = StdioServerParameters(
        command="uv", args=["run", "mcp-server-docker", "--read-only"]
    )
    async with Client(stdio_client(params), raise_exceptions=True) as client:
        tools = await client.list_tools()
    names = {tool.name for tool in tools.tools}
    assert len(names) == 23
    assert "docker_remove_container" not in names
    assert "docker_container_stats" in names


@pytest.mark.anyio
async def test_production_stdio_disable_destructive_exposes_only_safe_tools():
    params = StdioServerParameters(
        command="uv",
        args=["run", "mcp-server-docker", "--disable-destructive"],
    )
    async with Client(stdio_client(params), raise_exceptions=True) as client:
        tools = await client.list_tools()
        blocked = await client.call_tool(
            "docker_remove_container", {"container_id": "x"}
        )
    names = {tool.name for tool in tools.tools}
    assert len(names) == 33
    assert "docker_container_exec" in names
    assert {
        "docker_remove_container",
        "docker_remove_image",
        "docker_remove_network",
        "docker_remove_volume",
        "docker_recreate_container",
        "docker_container_prune",
        "docker_image_prune",
        "docker_volume_prune",
        "docker_system_prune",
        "docker_buildx_prune",
        "docker_buildx_build",
    }.isdisjoint(names)
    assert {"docker_create_container", "docker_stop_container"} <= names
    assert blocked.is_error
    assert "Unknown tool" in blocked.content[0].text


def _inspectable(calls, kind, attrs):
    obj = Object(calls)
    obj.attrs = attrs

    def get(name):
        calls.append((f"{kind}.get", name))
        return obj

    return get


@pytest.mark.anyio
async def test_network_inspect_returns_attributes_with_env_redacted(
    server, docker_client
):
    docker_client.networks.get = _inspectable(
        docker_client.calls,
        "networks",
        {
            "Name": "db-net",
            "Driver": "bridge",
            "IPAM": {"Config": [{"Subnet": "172.18.0.0/16"}]},
            "Config": {"Env": ["SECRET_TOKEN=abc123"]},
        },
    )
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_network_inspect", {"network_id": "db-net"}
        )
    assert docker_client.calls[-1] == ("networks.get", "db-net")
    assert result.structured_content == {
        "Name": "db-net",
        "Driver": "bridge",
        "IPAM": {"Config": [{"Subnet": "172.18.0.0/16"}]},
        "Config": {"Env": ["SECRET_TOKEN=<redacted>"]},
    }


@pytest.mark.anyio
async def test_volume_inspect_returns_attributes(server, docker_client):
    docker_client.volumes.get = _inspectable(
        docker_client.calls,
        "volumes",
        {
            "Name": "pgdata",
            "Driver": "local",
            "Mountpoint": "/var/lib/docker/volumes/pgdata/_data",
            "Labels": {"mcp-server-docker.project": "db"},
            "Options": None,
        },
    )
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_volume_inspect", {"volume_name": "pgdata"}
        )
    assert docker_client.calls[-1] == ("volumes.get", "pgdata")
    assert result.structured_content == {
        "Name": "pgdata",
        "Driver": "local",
        "Mountpoint": "/var/lib/docker/volumes/pgdata/_data",
        "Labels": {"mcp-server-docker.project": "db"},
        "Options": None,
    }


@pytest.mark.anyio
async def test_network_inspect_reports_unknown_network(server, docker_client):
    def fail(_name):
        raise docker.errors.NotFound("no such network")

    docker_client.networks.get = fail
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_network_inspect", {"network_id": "nope"}
        )
    assert result.is_error
    assert "no such network" in result.content[0].text


def _container(calls, attrs, status="running"):
    obj = Object(calls)
    obj.id = "abc123"
    obj.name = "web"
    obj.status = status
    obj.attrs = attrs
    return obj


@pytest.mark.anyio
async def test_container_health_summarises_a_healthy_container(server, docker_client):
    container = _container(
        docker_client.calls,
        {
            "RestartCount": 1,
            "Config": {
                "Image": "nginx:1.27",
                "Cmd": ["nginx", "-g", "daemon off;"],
                "Env": ["DB_PASSWORD=hunter2"],
            },
            "State": {
                "Status": "running",
                "Running": True,
                "Paused": False,
                "Restarting": False,
                "OOMKilled": False,
                "Dead": False,
                "Pid": 42,
                "ExitCode": 0,
                "Error": "",
                "StartedAt": "2026-11-14T10:00:00.123456789Z",
                "FinishedAt": "0001-01-01T00:00:00Z",
                "Health": {
                    "Status": "healthy",
                    "FailingStreak": 0,
                    "Log": [
                        {
                            "Start": "2026-11-14T10:00:10Z",
                            "End": "2026-11-14T10:00:11Z",
                            "ExitCode": 0,
                            "Output": "ok\n",
                        }
                    ],
                },
            },
        },
    )
    docker_client.containers.get = lambda _cid: container
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_container_health", {"container_id": "abc123"}
        )
    payload = result.structured_content
    assert payload["id"] == "abc123"
    assert payload["name"] == "web"
    assert payload["status"] == "running"
    assert payload["image"] == "nginx:1.27"
    assert payload["command"] == ["nginx", "-g", "daemon off;"]
    assert payload["restart_count"] == 1
    assert payload["exit_code"] == 0
    assert payload["oom_killed"] is False
    assert payload["started_at"] == "2026-11-14T10:00:00.123456789Z"
    assert payload["health"] == {
        "status": "healthy",
        "failing_streak": 0,
        "last_log": {
            "start": "2026-11-14T10:00:10Z",
            "end": "2026-11-14T10:00:11Z",
            "exit_code": 0,
            "output": "ok\n",
        },
    }
    assert "hunter2" not in json.dumps(payload)


@pytest.mark.anyio
async def test_container_health_reports_unhealthy_with_last_log(server, docker_client):
    container = _container(
        docker_client.calls,
        {
            "RestartCount": 3,
            "Config": {"Image": "api:2", "Cmd": ["python", "-m", "api"]},
            "State": {
                "Status": "running",
                "Running": True,
                "ExitCode": 0,
                "Health": {
                    "Status": "unhealthy",
                    "FailingStreak": 3,
                    "Log": [
                        {"ExitCode": 0, "Output": "ok\n"},
                        {"ExitCode": 1, "Output": "curl: (7) Failed to connect\n"},
                    ],
                },
            },
        },
    )
    docker_client.containers.get = lambda _cid: container
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_container_health", {"container_id": "abc123"}
        )
    health = result.structured_content["health"]
    assert health["status"] == "unhealthy"
    assert health["failing_streak"] == 3
    assert health["last_log"]["exit_code"] == 1
    assert health["last_log"]["output"] == "curl: (7) Failed to connect\n"
    assert result.structured_content["restart_count"] == 3


@pytest.mark.anyio
async def test_container_health_handles_non_running_container_without_health(
    server, docker_client
):
    container = _container(
        docker_client.calls,
        {
            "RestartCount": 0,
            "Config": {"Image": "worker:1", "Cmd": None, "Entrypoint": ["/w"]},
            "State": {
                "Status": "exited",
                "Running": False,
                "OOMKilled": True,
                "ExitCode": 137,
                "Error": "",
                "FinishedAt": "2026-11-14T11:00:00Z",
            },
        },
        status="exited",
    )
    docker_client.containers.get = lambda _cid: container
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_container_health", {"container_id": "abc123"}
        )
    payload = result.structured_content
    assert payload["status"] == "exited"
    assert payload["health"] is None
    assert payload["oom_killed"] is True
    assert payload["exit_code"] == 137
    assert payload["finished_at"] == "2026-11-14T11:00:00Z"
    assert payload["command"] == ["/w"]


EVENTS = [
    {"Type": "container", "Action": "start", "Actor": {"ID": "a1", "Attributes": {}}},
    {"Type": "container", "Action": "die", "Actor": {"ID": "a2", "Attributes": {}}},
    {"Type": "container", "Action": "oom", "Actor": {"ID": "a3", "Attributes": {}}},
]


def _events_stdout(entries):
    return "".join(f"{json.dumps(entry)}\n" for entry in entries)


@pytest.mark.anyio
async def test_events_list_passes_bounded_window_and_filters(server, docker_cli):
    docker_cli.responses.append(FakeProcess(stdout=_events_stdout(EVENTS[:2])))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool(
            "docker_events_list",
            {
                "window_seconds": 60,
                "limit": 10,
                "filters": {"type": ["container"], "event": ["die"], "label": ["a=b"]},
            },
        )
    command = docker_cli.calls[-1]
    assert command[1:5] == ["events", "--format", "json", "--since"]
    assert command[6] == "--until"
    assert int(command[7]) - int(command[5]) == 60
    assert command[8:] == [
        "--filter",
        "type=container",
        "--filter",
        "event=die",
        "--filter",
        "label=a=b",
    ]
    assert docker_cli.kwargs[-1]["timeout"] == 70
    payload = result.structured_content
    assert payload["count"] == 2
    assert payload["truncated"] is False
    assert payload["events"] == EVENTS[:2]
    assert payload["until"] == int(command[7])


@pytest.mark.anyio
async def test_events_list_defaults_to_a_bounded_window(server, docker_cli):
    docker_cli.responses.append(FakeProcess(stdout=""))
    async with Client(server, raise_exceptions=True) as client:
        await client.call_tool("docker_events_list", {})
    command = docker_cli.calls[-1]
    assert int(command[7]) - int(command[5]) == 900
    assert docker_cli.kwargs[-1]["timeout"] == 910


@pytest.mark.anyio
async def test_events_list_keeps_newest_events_and_flags_truncation(server, docker_cli):
    docker_cli.responses.append(FakeProcess(stdout=_events_stdout(EVENTS)))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_events_list", {"limit": 2})
    payload = result.structured_content
    assert payload["events"] == EVENTS[1:]
    assert payload["count"] == 2
    assert payload["truncated"] is True


@pytest.mark.anyio
async def test_events_list_empty_window_is_not_an_error(server, docker_cli):
    docker_cli.responses.append(FakeProcess(stdout=""))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_events_list", {"window_seconds": 1})
    assert result.is_error is False
    assert result.structured_content["events"] == []
    assert result.structured_content["count"] == 0
    assert result.structured_content["truncated"] is False


@pytest.mark.anyio
async def test_events_list_returns_partial_events_on_cli_timeout(
    server, docker_cli, monkeypatch
):
    def timeout(*_args, **kwargs):
        raise subprocess.TimeoutExpired(
            cmd="docker events",
            timeout=kwargs["timeout"],
            output=_events_stdout(EVENTS[:1]),
        )

    monkeypatch.setattr(server_module.subprocess, "run", timeout)
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_events_list", {})
    assert result.is_error is False
    assert result.structured_content["events"] == EVENTS[:1]
    assert result.structured_content["truncated"] is True
    assert result.structured_content["truncated_reason"] == "timeout"


@pytest.mark.anyio
async def test_events_list_reports_cli_errors(server, docker_cli):
    docker_cli.responses.append(FakeProcess(stdout="", stderr="boom\n", returncode=1))
    async with Client(server, raise_exceptions=True) as client:
        result = await client.call_tool("docker_events_list", {})
    assert result.is_error
    assert "boom" in result.content[0].text


@pytest.mark.anyio
async def test_events_list_includes_events_from_the_current_second(
    server, docker_cli, monkeypatch
):
    monkeypatch.setattr(server_module.time, "time", lambda: 1000.75)
    docker_cli.responses.append(FakeProcess(stdout=""))
    async with Client(server, raise_exceptions=True) as client:
        await client.call_tool("docker_events_list", {"window_seconds": 10})
    command = docker_cli.calls[-1]
    assert command[5] == "991"
    assert command[7] == "1001"


def _array_nodes_without_items(node: Any) -> list[Any]:
    found = []
    if isinstance(node, dict):
        if node.get("type") == "array" and "items" not in node:
            found.append(node)
        for value in node.values():
            found.extend(_array_nodes_without_items(value))
    elif isinstance(node, list):
        for value in node:
            found.extend(_array_nodes_without_items(value))
    return found


@pytest.mark.anyio
async def test_tool_input_schemas_have_items_for_every_array(server):
    async with Client(server, raise_exceptions=True) as client:
        tools = await client.list_tools()
    offenders = {
        tool.name: _array_nodes_without_items(tool.input_schema) for tool in tools.tools
    }
    assert {name: nodes for name, nodes in offenders.items() if nodes} == {}


@pytest.mark.parametrize("factory", [bytes, bytearray, memoryview])
@pytest.mark.parametrize("size", [0, 20480, 20481, 40000])
def test_attached_output_preserves_bounded_suffix_and_original_size(factory, size):
    raw = b"x" * size
    result = server_module._run_result(factory(raw), detach=False)
    assert result == {
        "mode": "attached",
        "output": raw[-server_module.MAX_ATTACHED_TEXT_BYTES :].decode(
            "utf-8", errors="replace"
        ),
        "truncated": size > server_module.MAX_ATTACHED_TEXT_BYTES,
        "bytes": size,
    }


def test_attached_output_replaces_a_partial_utf8_sequence_at_the_bound():
    raw = b"prefix" + "€".encode() + b"x" * 20479
    result = server_module._run_result(raw, detach=False)
    assert result["output"] == "\ufffd" + "x" * 20479
    assert result["truncated"] is True
    assert result["bytes"] == len(raw)


def test_attached_output_rejects_unexpected_result_types():
    with pytest.raises(TypeError, match="unexpected type"):
        server_module._run_result(object(), detach=False)


def test_normalize_ports_restores_the_host_ip_tuple_form():
    assert server_module._normalize_ports(
        {
            "80/tcp": ["127.0.0.1", 8080],
            "81/tcp": 8081,
            "82/tcp": [8082, 8083],
            "83/tcp": None,
        }
    ) == {
        "80/tcp": ("127.0.0.1", 8080),
        "81/tcp": 8081,
        "82/tcp": [8082, 8083],
        "83/tcp": None,
    }
    assert server_module._normalize_ports(None) is None
