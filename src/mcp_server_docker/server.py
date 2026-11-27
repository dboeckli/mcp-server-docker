"""MCPServer v2 implementation for Docker."""

import json
import shutil
import subprocess
import time
from collections.abc import AsyncIterator, Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from functools import wraps
from typing import Annotated, Any, Literal

import docker
from mcp.server import MCPServer
from mcp.server.mcpserver import Context
from mcp.server.mcpserver.exceptions import ToolError
from mcp.shared.exceptions import MCPError
from mcp.types import CallToolResult, TextContent, ToolAnnotations
from pydantic import BaseModel, Field

from mcp_server_docker._version import __version__
from mcp_server_docker.output_schemas import docker_to_dict
from mcp_server_docker.redaction import redact_env
from mcp_server_docker.settings import ServerSettings, is_tool_enabled


@dataclass
class AppContext:
    """State made available to handlers for one running server."""

    docker: docker.DockerClient


class ListContainersFilters(BaseModel):
    label: list[str] | None = Field(
        None, description="Filter by label, either `key` or `key=value` format"
    )


class ListImagesFilters(BaseModel):
    dangling: bool | None = Field(None, description="Show dangling images")
    label: list[str] | None = Field(
        None, description="Filter by label, either `key` or `key=value` format"
    )


class ListNetworksFilter(BaseModel):
    label: list[str] | None = Field(
        None, description="Filter by label, either `key` or `key=value` format"
    )


class ListEventsFilters(BaseModel):
    type: list[str] | None = Field(
        None, description="Filter by object type (container, image, volume, network)"
    )
    event: list[str] | None = Field(None, description="Filter by event action")
    container: list[str] | None = Field(None, description="Filter by container")
    image: list[str] | None = Field(None, description="Filter by image")
    label: list[str] | None = Field(
        None, description="Filter by label, either `key` or `key=value` format"
    )


ContainerID = Annotated[str, Field(description="Container ID or name")]
ImageName = Annotated[str, Field(description="Docker image name")]
Detach = Annotated[bool, Field(description="Run container in the background")]
Entrypoint = Annotated[str | None, Field(description="Entrypoint to run in container")]
ContainerCommand = Annotated[
    str | None, Field(description="Command to run in container")
]
NetworkName = Annotated[
    str | None, Field(description="Network to attach the container to")
]
Environment = Annotated[
    dict[str, str] | None, Field(description="Environment variables dictionary")
]
PortBindings = Annotated[
    dict[str, int | list[int | str] | None] | None,
    Field(description="Container-to-host port bindings"),
]
VolumeMappings = Annotated[
    dict[str, dict[str, str]] | list[str] | None, Field(description="Volume mappings")
]
ContainerLabels = Annotated[
    dict[str, str] | list[str] | None, Field(description="Container labels")
]
AutoRemove = Annotated[bool, Field(description="Automatically remove the container")]
Format = Annotated[
    Literal["summary", "full"],
    Field(
        description=(
            "Output verbosity. `summary` returns a compact `docker ps`-style row "
            "(no health-check logs, labels or image digests); `full` returns the "
            "inspect-level object. Defaults to `summary` for listings."
        )
    ),
]


def _client(ctx: Context[AppContext]) -> docker.DockerClient:
    return ctx.request_context.lifespan_context.docker


def _engine_filters(model: BaseModel | None) -> dict[str, Any] | None:
    """Drop unset filter fields instead of sending them to the engine as null."""
    if model is None:
        return None
    return model.model_dump(exclude_none=True) or None


def _container_label_filters(
    filters: ListContainersFilters | None,
) -> dict[str, dict[str, bool]] | None:
    """Encode container label filters in the map form the Docker CLI uses.

    docker-py's convert_filters() sends {"label": ["key=value"]}. Docker Desktop
    only reveals the containers it hides (Kubernetes pods) for the map form
    {"label": {"key=value": true}}, so filtered listings use the raw API.
    """
    if filters is None or not filters.label:
        return None
    return {"label": {label: True for label in filters.label}}


def _normalize_ports(
    ports: dict[str, int | list[int | str] | None] | None,
) -> dict[str, Any] | None:
    """Restore docker-py's ``(host_ip, host_port)`` tuple from a JSON array.

    MCP clients can only send arrays, so the schema accepts a two-item list for
    the host-IP form and this converts it back before the SDK sees it.
    """
    if ports is None:
        return None
    normalized: dict[str, Any] = {}
    for container_port, binding in ports.items():
        if (
            isinstance(binding, list)
            and len(binding) == 2
            and isinstance(binding[0], str)
            and isinstance(binding[1], int)
        ):
            normalized[container_port] = (binding[0], binding[1])
        else:
            normalized[container_port] = binding
    return normalized


_CLI_ENCODING = "utf-8"


def _decode_cli_output(data: bytes) -> str:
    """Decode CLI or container output as UTF-8, replacing malformed bytes."""
    return data.decode(_CLI_ENCODING, errors="replace")


MAX_ATTACHED_TEXT_BYTES = 20 * 1024


def _run_result(value: Any, *, detach: bool) -> dict[str, Any]:
    """Normalize Docker SDK run results for attached and detached execution."""
    if detach:
        return docker_to_dict(value)
    if isinstance(value, (bytes, bytearray, memoryview)):
        raw = bytes(value)
        total = len(raw)
        selected = (
            raw[-MAX_ATTACHED_TEXT_BYTES:] if total > MAX_ATTACHED_TEXT_BYTES else raw
        )
        return {
            "mode": "attached",
            "output": _decode_cli_output(selected),
            "truncated": total > MAX_ATTACHED_TEXT_BYTES,
            "bytes": total,
        }
    raise TypeError(f"Attached Docker run returned unexpected type: {type(value)}")


MAX_LOG_TEXT_BYTES = 20 * 1024


def _bounded_log_output(raw: bytes) -> dict[str, Any]:
    """Return a bounded text suffix with original size and truncation evidence."""
    total = len(raw)
    selected = raw[-MAX_LOG_TEXT_BYTES:] if total > MAX_LOG_TEXT_BYTES else raw
    return {
        "logs": _decode_cli_output(selected).split("\n"),
        "truncated": total > MAX_LOG_TEXT_BYTES,
        "bytes": total,
    }


def _run_docker(
    *args: str, combine_stderr: bool = False, timeout: float | None = None
) -> str:
    """Run the docker CLI and return stdout, raising on failure."""
    executable = shutil.which("docker")
    if executable is None:
        raise RuntimeError("docker CLI not found on PATH")
    result = subprocess.run(
        [executable, *args],
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT if combine_stderr else subprocess.PIPE,
        text=True,
        encoding=_CLI_ENCODING,
        errors="replace",
        timeout=timeout,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr if result.stderr is not None else result.stdout
        raise RuntimeError(detail.strip() or f"docker {' '.join(args)} failed")
    return result.stdout


def _parse_json_stream(output: str) -> list[dict[str, Any]]:
    """Parse buildx output from a JSON document or a JSON-lines stream."""
    text = output.strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError:
        data = [json.loads(line) for line in text.splitlines() if line.strip()]
    if isinstance(data, dict):
        return [data]
    if isinstance(data, list) and all(isinstance(item, dict) for item in data):
        return data
    raise RuntimeError("unexpected buildx JSON output")


_DU_FIELDS = ("shared", "private", "reclaimable", "total")


def _parse_du_summary(output: str) -> dict[str, str | None]:
    values: dict[str, str | None] = {field: None for field in _DU_FIELDS}
    for line in output.splitlines():
        label, separator, value = line.partition(":")
        key = label.strip().lower()
        if separator and key in values:
            values[key] = value.strip()
    return values


@asynccontextmanager
async def lifespan(_: MCPServer[AppContext]) -> AsyncIterator[AppContext]:
    """Create and close the Docker client for one server lifetime."""
    client = docker.from_env()
    try:
        yield AppContext(docker=client)
    finally:
        client.close()


app = MCPServer("docker-server", version=__version__, lifespan=lifespan)
settings = ServerSettings.from_env_and_argv()


class ToolRuntimeError(ToolError, RuntimeError):
    """A tool failure whose message is safe to surface to the model."""


def _json_list_result(items: list[Any]) -> CallToolResult:
    """Return a list as one JSON array block instead of one block per element.

    The MCP framework unrolls a list result into a text block per element, which
    leaves clients with concatenated JSON objects instead of a single document.
    Emitting one block keeps the array contract and also covers empty lists,
    which would otherwise produce no content at all.
    """
    return CallToolResult(
        content=[
            TextContent(type="text", text=json.dumps(items, indent=2, default=str))
        ],
        structured_content={"result": items},
    )


def tool(
    *args: Any, **kwargs: Any
) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Register a tool when the current server settings allow it."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        @wraps(fn)
        def call(*fn_args: Any, **fn_kwargs: Any) -> Any:
            """Call the tool body, mapping failures to model-visible errors."""
            try:
                return fn(*fn_args, **fn_kwargs)
            except (MCPError, ToolError):
                raise
            except Exception as exc:
                raise ToolRuntimeError(str(exc)) from exc

        @wraps(fn)
        def mcp_tool(*fn_args: Any, **fn_kwargs: Any) -> Any:
            """Registered entry point: shapes list results for MCP clients."""
            result = call(*fn_args, **fn_kwargs)
            return _json_list_result(result) if isinstance(result, list) else result

        name = kwargs.get("name") or fn.__name__
        if is_tool_enabled(name, kwargs.get("annotations"), settings):
            app.tool(*args, **kwargs)(mcp_tool)
        # Direct callers keep the plain Python return value.
        return call

    return decorator


@app.prompt(
    name="docker_compose", description="Treat the LLM like a Docker Compose manager"
)
def docker_compose(ctx: Context, name: str, containers: str) -> str:
    client = ctx.request_context.lifespan_context.docker
    project_label = f"mcp-server-docker.project={name}"
    existing_containers = client.containers.list(filters={"label": project_label})
    volumes = client.volumes.list(filters={"label": project_label})
    networks = client.networks.list(filters={"label": project_label})
    return f"""
You are going to act as a Docker Compose manager, using the Docker Tools
available to you. Instead of being provided a `docker-compose.yml` file,
you will be given instructions in plain language, and interact with the
user through a plan+apply loop, akin to how Terraform operates.

Every Docker resource you create must be assigned the following label:

{project_label}

You should use this label to filter resources when possible.

Every Docker resource you create must also be prefixed with the project name, followed by a dash (`-`):

{name}-{{ResourceName}}

Here are the resources currently present in the project, based on the presence of the above label:

<BEGIN CONTAINERS>
{json.dumps([docker_to_dict(c) for c in existing_containers], indent=2)}
<END CONTAINERS>
<BEGIN VOLUMES>
{json.dumps([docker_to_dict(v) for v in volumes], indent=2)}
<END VOLUMES>
<BEGIN NETWORKS>
{json.dumps([docker_to_dict(n) for n in networks], indent=2)}
<END NETWORKS>

Do not retry the same failed action more than once. Prefer terminating your output
when presented with 3 errors in a row, and ask a clarifying question to
form better inputs or address the error.

For container images, always prefer using the `latest` image tag, unless the user specifies a tag specifically.
So if a user asks to deploy Nginx, you should pull `nginx:latest`.

Below is a description of the state of the Docker resources which the user would like you to manage:

<BEGIN DOCKER-RESOURCES>
{containers}
<END DOCKER-RESOURCES>

Respond to this message with a plan of what you will do, in the EXACT format below:

<BEGIN FORMAT>
## Introduction

I will be assisting with deploying Docker containers for project: `{name}`.

### Plan+Apply Loop

I will run in a plan+apply loop when you request changes to the project. This is
to ensure that you are aware of the changes I am about to make, and to give you
the opportunity to ask questions or make tweaks.

Instruct me to apply immediately (without confirming the plan with you) when you desire to do so.

## Commands

Instruct me with the following commands at any point:

- `help`: print this list of commands
- `apply`: apply a given plan
- `down`: stop containers in the project
- `ps`: list containers in the project
- `quiet`: turn on quiet mode (default)
- `verbose`: turn on verbose mode (I will explain a lot!)
- `destroy`: produce a plan to destroy all resources in the project

## Plan

I plan to take the following actions:

1. CREATE ...
2. READ ...
3. UPDATE ...
4. DESTROY ...
5. RECREATE ...
...
N. ...

Respond `apply` to apply this plan. Otherwise, provide feedback and I will present you with an updated plan.
<END FORMAT>

Always apply a plan in dependency order. For example, if you are creating a container that depends on a
database, create the database first, and abort the apply if dependency creation fails. Likewise, 
destruction should occur in the reverse dependency order, and be aborted if destroying a particular resource fails.

Plans should only create, update, or destroy resources in the project. Relatedly, "recreate" should
be used to indicate a destroy followed by a create; always prefer udpating a resource when possible,
only recreating it if required (e.g. for immutable resources like containers).

If the project already exists (as indicated by the presence of resources above) and your plan would
produce no changes, simply respond with "No changes to make; project is up-to-date." If the user requests
changes that would render a resource obsolete (e.g. an unused volume), you should destroy the resource.

If you produce a plan and the next user message is not `apply`, simply drop the plan and inform
the user that they must explicitly include "apply" in the message. Only
apply a plan if it is contained in your latest message, otherwise ask the user to provide
their desires for the new plan.

IMPORTANT: maintain brevvity throughout your responses, unless instructed to be verbose.

The following are guidelines for you to follow when interacting with Docker Tools:

- Always prefer `docker_run_container` for starting a container, instead of `docker_create_container`+`docker_start_container`.
- Always prefer `docker_recreate_container` for updating a container, instead of `docker_stop_container`+`docker_remove_container`+`docker_run_container`.
"""


@app.resource(
    "docker://containers/{container_id}/logs",
    name="Container logs",
    description="Live logs for a container",
    mime_type="text/plain",
)
def container_logs(container_id: str, ctx: Context) -> str:
    container = ctx.request_context.lifespan_context.docker.containers.get(container_id)
    return _decode_cli_output(container.logs(tail=100))


def _one_shot_stats(client: docker.DockerClient, container_id: str) -> dict[str, Any]:
    return client.containers.get(container_id).stats(stream=False)


@app.resource(
    "docker://containers/{container_id}/stats",
    name="Container stats",
    description="Live resource usage stats for a container",
    mime_type="application/json",
)
def container_stats_resource(container_id: str, ctx: Context) -> dict[str, Any]:
    return _one_shot_stats(ctx.request_context.lifespan_context.docker, container_id)


@tool(
    description="List all Docker containers (same container set as `docker ps`)",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_list_containers(
    ctx: Context[AppContext],
    all: Annotated[
        bool, Field(description="Show all containers (default shows just running)")
    ] = False,
    filters: Annotated[
        ListContainersFilters | None, Field(description="Filter containers")
    ] = None,
    format: Format = "summary",
) -> list[dict[str, Any]]:
    client = _client(ctx)
    label_filters = _container_label_filters(filters)
    if label_filters is None:
        containers = client.containers.list(all=all, filters=None)
    else:
        api = client.api
        params = {"all": 1 if all else 0, "filters": json.dumps(label_filters)}
        hits = api._result(api.get(api._url("/containers/json"), params=params), True)
        containers = [client.containers.get(hit["Id"]) for hit in hits]
    return [docker_to_dict(container, format=format) for container in containers]


@tool(
    description="Create a new Docker container",
    annotations=ToolAnnotations(
        destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_create_container(
    ctx: Context[AppContext],
    image: ImageName,
    detach: Annotated[
        bool, Field(description="Run container in the background")
    ] = True,
    name: Annotated[str | None, Field(description="Container name")] = None,
    entrypoint: Annotated[
        str | None, Field(description="Entrypoint to run in container")
    ] = None,
    command: Annotated[
        str | None, Field(description="Command to run in container")
    ] = None,
    network: Annotated[
        str | None, Field(description="Network to attach the container to")
    ] = None,
    environment: Annotated[
        dict[str, str] | None, Field(description="Environment variables dictionary")
    ] = None,
    ports: Annotated[
        dict[str, int | list[int | str] | None] | None,
        Field(description="Container-to-host port bindings"),
    ] = None,
    volumes: Annotated[
        dict[str, dict[str, str]] | list[str] | None,
        Field(description="Volume mappings"),
    ] = None,
    labels: Annotated[
        dict[str, str] | list[str] | None, Field(description="Container labels")
    ] = None,
    auto_remove: Annotated[
        bool, Field(description="Automatically remove the container")
    ] = False,
) -> dict[str, Any]:
    return docker_to_dict(
        _client(ctx).containers.create(
            image=image,
            detach=detach,
            name=name,
            entrypoint=entrypoint,
            command=command,
            network=network,
            environment=environment,
            ports=_normalize_ports(ports),
            volumes=volumes,
            labels=labels,
            auto_remove=auto_remove,
        )
    )


@tool(
    description="Run an image in a new Docker container (preferred over `docker_create_container` + `docker_start_container`)",
    annotations=ToolAnnotations(
        destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_run_container(
    ctx: Context[AppContext],
    image: ImageName,
    detach: Annotated[
        bool, Field(description="Run container in the background")
    ] = True,
    name: Annotated[str | None, Field(description="Container name")] = None,
    entrypoint: Annotated[
        str | None, Field(description="Entrypoint to run in container")
    ] = None,
    command: Annotated[
        str | None, Field(description="Command to run in container")
    ] = None,
    network: Annotated[
        str | None, Field(description="Network to attach the container to")
    ] = None,
    environment: Annotated[
        dict[str, str] | None, Field(description="Environment variables dictionary")
    ] = None,
    ports: Annotated[
        dict[str, int | list[int | str] | None] | None,
        Field(description="Container-to-host port bindings"),
    ] = None,
    volumes: Annotated[
        dict[str, dict[str, str]] | list[str] | None,
        Field(description="Volume mappings"),
    ] = None,
    labels: Annotated[
        dict[str, str] | list[str] | None, Field(description="Container labels")
    ] = None,
    auto_remove: Annotated[
        bool, Field(description="Automatically remove the container")
    ] = False,
) -> dict[str, Any]:
    result = _client(ctx).containers.run(
        image=image,
        detach=detach,
        name=name,
        entrypoint=entrypoint,
        command=command,
        network=network,
        environment=environment,
        ports=_normalize_ports(ports),
        volumes=volumes,
        labels=labels,
        auto_remove=auto_remove,
    )
    return _run_result(result, detach=detach)


@tool(
    description="Stop and remove a container, then run a new container. Fails if the container does not exist.",
    annotations=ToolAnnotations(
        destructive_hint=True, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_recreate_container(
    ctx: Context[AppContext],
    image: ImageName,
    container_id: ContainerID | None = None,
    name: Annotated[str | None, Field(description="Container name")] = None,
    detach: Detach = True,
    entrypoint: Entrypoint = None,
    command: ContainerCommand = None,
    network: NetworkName = None,
    environment: Environment = None,
    ports: PortBindings = None,
    volumes: VolumeMappings = None,
    labels: ContainerLabels = None,
    auto_remove: AutoRemove = False,
) -> dict[str, Any]:
    if container_id is None and name is None:
        raise ValueError(
            "container_id or name is required for identifying the container to stop+remove"
        )
    old = _client(ctx).containers.get(container_id or name)
    old.stop()
    old.remove()
    return docker_to_dict(
        _client(ctx).containers.run(
            image=image,
            detach=detach,
            name=name,
            entrypoint=entrypoint,
            command=command,
            network=network,
            environment=environment,
            ports=_normalize_ports(ports),
            volumes=volumes,
            labels=labels,
            auto_remove=auto_remove,
        )
    )


@tool(
    description="Start a Docker container",
    annotations=ToolAnnotations(
        destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_start_container(
    ctx: Context[AppContext], container_id: ContainerID
) -> dict[str, Any]:
    container = _client(ctx).containers.get(container_id)
    container.start()
    return docker_to_dict(container)


@tool(
    description="Fetch logs for a Docker container",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_fetch_container_logs(
    ctx: Context[AppContext],
    container_id: ContainerID,
    tail: Annotated[
        int | Literal["all"],
        Field(description="Number of lines to show from the end"),
    ] = 100,
) -> dict[str, Any]:
    raw = _client(ctx).containers.get(container_id).logs(tail=tail)
    return _bounded_log_output(raw)


@tool(
    description="Stop a Docker container",
    annotations=ToolAnnotations(
        destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_stop_container(
    ctx: Context[AppContext], container_id: ContainerID
) -> dict[str, Any]:
    container = _client(ctx).containers.get(container_id)
    container.stop()
    return docker_to_dict(container)


@tool(
    description="Remove a Docker container",
    annotations=ToolAnnotations(
        destructive_hint=True, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_remove_container(
    ctx: Context[AppContext],
    container_id: ContainerID,
    force: Annotated[bool, Field(description="Force remove the container")] = False,
) -> dict[str, Any]:
    container = _client(ctx).containers.get(container_id)
    container.remove(force=force)
    return docker_to_dict(container, {"status": "removed"})


@tool(
    description="Inspect a Docker container with environment values redacted",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_container_inspect(
    ctx: Context[AppContext],
    container_id: ContainerID,
) -> dict[str, Any]:
    return redact_env(_client(ctx).containers.get(container_id).attrs)


_HEALTH_LOG_OUTPUT_LIMIT = 1000


@tool(
    description=(
        "Summarise container health, restart count and exit state "
        "without environment values"
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_container_health(
    ctx: Context[AppContext],
    container_id: ContainerID,
) -> dict[str, Any]:
    container = _client(ctx).containers.get(container_id)
    attrs = container.attrs
    config = attrs.get("Config") or {}
    state = attrs.get("State") or {}
    health = state.get("Health")
    last_log = None
    if isinstance(health, dict):
        entries = health.get("Log") or []
        if entries:
            entry = entries[-1]
            last_log = {
                "start": entry.get("Start"),
                "end": entry.get("End"),
                "exit_code": entry.get("ExitCode"),
                "output": (entry.get("Output") or "")[:_HEALTH_LOG_OUTPUT_LIMIT],
            }
    return {
        "id": container.id,
        "name": container.name,
        "status": container.status,
        "image": config.get("Image"),
        "command": config.get("Cmd") or config.get("Entrypoint") or [],
        "restart_count": attrs.get("RestartCount"),
        "exit_code": state.get("ExitCode"),
        "oom_killed": state.get("OOMKilled"),
        "error": state.get("Error"),
        "dead": state.get("Dead"),
        "paused": state.get("Paused"),
        "running": state.get("Running"),
        "restarting": state.get("Restarting"),
        "pid": state.get("Pid"),
        "started_at": state.get("StartedAt"),
        "finished_at": state.get("FinishedAt"),
        "health": None
        if not isinstance(health, dict)
        else {
            "status": health.get("Status"),
            "failing_streak": health.get("FailingStreak"),
            "last_log": last_log,
        },
    }


@tool(
    description="List the processes running in a Docker container",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_container_processes(
    ctx: Context[AppContext],
    container_id: ContainerID,
) -> dict[str, Any]:
    return _client(ctx).containers.get(container_id).top()


@tool(
    description=(
        "Show a one-shot CPU, memory, network and block-IO snapshot for a container"
    ),
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_container_stats(
    ctx: Context[AppContext],
    container_id: ContainerID,
) -> dict[str, Any]:
    return _one_shot_stats(_client(ctx), container_id)


@tool(
    description="List Docker images",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_list_images(
    ctx: Context[AppContext],
    name: Annotated[
        str | None, Field(description="Filter images by repository name")
    ] = None,
    all: Annotated[
        bool, Field(description="Show all images (default hides intermediate)")
    ] = False,
    filters: Annotated[
        ListImagesFilters | None, Field(description="Filter images")
    ] = None,
    format: Format = "summary",
) -> list[dict[str, Any]]:
    return [
        docker_to_dict(image, format=format)
        for image in _client(ctx).images.list(
            name=name, all=all, filters=_engine_filters(filters)
        )
    ]


@tool(
    description="Pull a Docker image",
    annotations=ToolAnnotations(
        destructive_hint=False, idempotent_hint=False, open_world_hint=True
    ),
)
def docker_pull_image(
    ctx: Context[AppContext],
    repository: Annotated[str, Field(description="Image repository")],
    tag: Annotated[str | None, Field(description="Image tag")] = "latest",
) -> dict[str, Any]:
    return docker_to_dict(_client(ctx).images.pull(repository, tag=tag))


@tool(
    description="Push a Docker image",
    annotations=ToolAnnotations(
        destructive_hint=False, idempotent_hint=False, open_world_hint=True
    ),
)
def docker_push_image(
    ctx: Context[AppContext],
    repository: Annotated[str, Field(description="Image repository")],
    tag: Annotated[str | None, Field(description="Image tag")] = "latest",
) -> dict[str, str | None]:
    _client(ctx).images.push(repository, tag=tag)
    return {"status": "pushed", "repository": repository, "tag": tag}


@tool(
    description="Build a Docker image from a Dockerfile",
    annotations=ToolAnnotations(
        destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_build_image(
    ctx: Context[AppContext],
    path: Annotated[str, Field(description="Path to build context")],
    tag: Annotated[str, Field(description="Image tag")],
    dockerfile: Annotated[str | None, Field(description="Path to Dockerfile")] = None,
) -> dict[str, Any]:
    image, logs = _client(ctx).images.build(
        path=path, tag=tag, dockerfile=dockerfile, rm=True, forcerm=True
    )
    return {"image": docker_to_dict(image), "logs": list(logs)}


@tool(
    description="Remove a Docker image",
    annotations=ToolAnnotations(
        destructive_hint=True, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_remove_image(
    ctx: Context[AppContext],
    image: Annotated[str, Field(description="Image ID or name")],
    force: Annotated[bool, Field(description="Force remove the image")] = False,
) -> dict[str, str]:
    _client(ctx).images.remove(image=image, force=force)
    return {"status": "removed", "image": image}


@tool(
    description="Inspect a Docker image with environment values redacted",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_image_inspect(
    ctx: Context[AppContext],
    image: Annotated[str, Field(description="Image ID or name")],
) -> dict[str, Any]:
    return redact_env(_client(ctx).images.get(image).attrs)


@tool(
    description="Show the layer history of a Docker image",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_image_history(
    ctx: Context[AppContext],
    image: Annotated[str, Field(description="Image ID or name")],
) -> list[dict[str, Any]]:
    return _client(ctx).images.get(image).history()


@tool(
    description="List Docker Buildx builder instances",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_buildx_list() -> list[dict[str, Any]]:
    return _parse_json_stream(_run_docker("buildx", "ls", "--format", "json"))


@tool(
    description="Show Docker Buildx cache usage per builder",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_buildx_du(
    builder: Annotated[
        str | None, Field(description="Builder instance to query")
    ] = None,
    verbose: Annotated[
        bool, Field(description="Include individual cache records")
    ] = False,
) -> list[dict[str, Any]]:
    builders = (
        [{"Name": builder, "Current": None}]
        if builder is not None
        else _parse_json_stream(_run_docker("buildx", "ls", "--format", "json"))
    )
    results: list[dict[str, Any]] = []
    for entry in builders:
        name = entry.get("Name") or entry.get("name")
        result: dict[str, Any] = {
            "builder": name,
            "current": entry.get("Current", entry.get("current")),
        }
        try:
            result.update(
                _parse_du_summary(_run_docker("buildx", "du", "--builder", name))
            )
            if verbose:
                result["records"] = _parse_json_stream(
                    _run_docker("buildx", "du", "--builder", name, "--format", "json")
                )
        except RuntimeError as exc:
            result["error"] = str(exc)
        results.append(result)
    return results


@tool(
    description="Inspect a Docker Buildx builder instance",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_buildx_inspect(
    builder: Annotated[
        str | None, Field(description="Builder instance to inspect")
    ] = None,
) -> str:
    args = ["buildx", "inspect"]
    if builder is not None:
        args += ["--builder", builder]
    return _run_docker(*args, combine_stderr=True)


@tool(
    description="List Docker Buildx build records",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_buildx_history(
    builder: Annotated[
        str | None, Field(description="Builder instance to query")
    ] = None,
) -> list[dict[str, Any]]:
    args = ["buildx", "history", "ls", "--format", "json"]
    if builder is not None:
        args += ["--builder", builder]
    return _parse_json_stream(_run_docker(*args))


@tool(
    description="Show the logs of a Docker Buildx build record",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_buildx_logs(
    ref: Annotated[str, Field(description="Build record reference or build ID")],
    builder: Annotated[
        str | None, Field(description="Builder instance to query")
    ] = None,
    progress: Annotated[
        Literal["plain", "rawjson", "tty"],
        Field(description="Progress output type"),
    ] = "plain",
) -> str:
    build_id = ref.rsplit("/", 1)[-1]
    if progress == "tty":
        raise RuntimeError("progress='tty' needs a terminal; use 'plain' or 'rawjson'")
    args = ["buildx", "history", "logs", build_id]
    if builder is not None:
        args += ["--builder", builder]
    args += ["--progress", progress]
    return _run_docker(*args, combine_stderr=True)


@tool(
    description="Show Docker disk usage, including reclaimable space",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_system_df(
    verbose: Annotated[
        bool, Field(description="Include detailed per-object usage")
    ] = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "summary": _parse_json_stream(_run_docker("system", "df", "--format", "json"))
    }
    if verbose:
        detail = _run_docker("system", "df", "-v", "--format", "json")
        result["detail"] = json.loads(detail) if detail.strip() else {}
    return result


_EVENTS_WINDOW_LIMITS = (1, 86400)
_EVENTS_LIMIT_LIMITS = (1, 1000)
_EVENTS_TIMEOUT_MARGIN = 10


def _clamp(value: int, bounds: tuple[int, int]) -> int:
    lower, upper = bounds
    return max(lower, min(int(value), upper))


@tool(
    description=("List recent Docker events for a bounded window, newest first"),
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_events_list(
    window_seconds: Annotated[
        int, Field(description="How far back to look, in seconds (1-86400)")
    ] = 900,
    limit: Annotated[
        int, Field(description="Maximum number of events to return (1-1000)")
    ] = 100,
    filters: Annotated[
        ListEventsFilters | None, Field(description="Filter events")
    ] = None,
) -> dict[str, Any]:
    window = _clamp(window_seconds, _EVENTS_WINDOW_LIMITS)
    maximum = _clamp(limit, _EVENTS_LIMIT_LIMITS)
    # Round the window end up: `--until` compares with sub-second precision on
    # the daemon side, so truncating to the current second drops events from the
    # last partial second. The extra wait is below one second.
    until = int(time.time()) + 1
    since = until - window
    args = [
        "events",
        "--format",
        "json",
        "--since",
        str(since),
        "--until",
        str(until),
    ]
    for key, values in (
        filters.model_dump(exclude_none=True) if filters else {}
    ).items():
        for value in values:
            args += ["--filter", f"{key}={value}"]

    timed_out = False
    try:
        output = _run_docker(*args, timeout=window + _EVENTS_TIMEOUT_MARGIN)
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        partial = exc.output or ""
        output = _decode_cli_output(partial) if isinstance(partial, bytes) else partial

    events = _parse_json_stream(output)
    truncated = len(events) > maximum
    result: dict[str, Any] = {
        "events": events[-maximum:],
        "count": min(len(events), maximum),
        "truncated": truncated or timed_out,
        "since": since,
        "until": until,
    }
    if timed_out:
        result["truncated_reason"] = "timeout"
    return result


@tool(
    description="List Docker networks",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_list_networks(
    ctx: Context[AppContext],
    filters: Annotated[
        ListNetworksFilter | None, Field(description="Filter networks")
    ] = None,
) -> list[dict[str, Any]]:
    return [
        docker_to_dict(network)
        for network in _client(ctx).networks.list(filters=_engine_filters(filters))
    ]


@tool(
    description="Create a Docker network",
    annotations=ToolAnnotations(
        destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_create_network(
    ctx: Context[AppContext],
    name: Annotated[str, Field(description="Network name")],
    driver: Annotated[str | None, Field(description="Network driver")] = "bridge",
    internal: Annotated[bool, Field(description="Create an internal network")] = False,
    labels: Annotated[
        dict[str, str] | None, Field(description="Network labels")
    ] = None,
) -> dict[str, Any]:
    return docker_to_dict(
        _client(ctx).networks.create(
            name=name, driver=driver, internal=internal, labels=labels
        )
    )


@tool(
    description="Remove a Docker network",
    annotations=ToolAnnotations(
        destructive_hint=True, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_remove_network(
    ctx: Context[AppContext],
    network_id: Annotated[str, Field(description="Network ID or name")],
) -> dict[str, Any]:
    network = _client(ctx).networks.get(network_id)
    network.remove()
    return docker_to_dict(network)


@tool(
    description="Inspect a Docker network with environment values redacted",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_network_inspect(
    ctx: Context[AppContext],
    network_id: Annotated[str, Field(description="Network ID or name")],
) -> dict[str, Any]:
    return redact_env(_client(ctx).networks.get(network_id).attrs)


@tool(
    description="List Docker volumes",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_list_volumes(
    ctx: Context[AppContext], format: Format = "summary"
) -> list[dict[str, Any]]:
    return [
        docker_to_dict(volume, format=format) for volume in _client(ctx).volumes.list()
    ]


@tool(
    description="Create a Docker volume",
    annotations=ToolAnnotations(
        destructive_hint=False, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_create_volume(
    ctx: Context[AppContext],
    name: Annotated[str, Field(description="Volume name")],
    driver: Annotated[str | None, Field(description="Volume driver")] = "local",
    labels: Annotated[dict[str, str] | None, Field(description="Volume labels")] = None,
) -> dict[str, Any]:
    return docker_to_dict(
        _client(ctx).volumes.create(name=name, driver=driver, labels=labels)
    )


@tool(
    description="Remove a Docker volume",
    annotations=ToolAnnotations(
        destructive_hint=True, idempotent_hint=False, open_world_hint=False
    ),
)
def docker_remove_volume(
    ctx: Context[AppContext],
    volume_name: Annotated[str, Field(description="Volume name")],
    force: Annotated[bool, Field(description="Force remove the volume")] = False,
) -> dict[str, Any]:
    volume = _client(ctx).volumes.get(volume_name)
    volume.remove(force=force)
    return docker_to_dict(volume)


@tool(
    description="Inspect a Docker volume with environment values redacted",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_volume_inspect(
    ctx: Context[AppContext],
    volume_name: Annotated[str, Field(description="Volume name")],
) -> dict[str, Any]:
    return redact_env(_client(ctx).volumes.get(volume_name).attrs)


_SYSTEM_INFO_KEYS = (
    "ServerVersion",
    "OperatingSystem",
    "OSType",
    "Architecture",
    "KernelVersion",
    "NCPU",
    "MemTotal",
    "Containers",
    "ContainersRunning",
    "ContainersPaused",
    "ContainersStopped",
    "Images",
    "Driver",
    "DriverStatus",
    "Plugins",
    "LoggingDriver",
    "CgroupDriver",
    "CgroupVersion",
    "DockerRootDir",
)


@tool(
    description="Show the Docker server version",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_version(ctx: Context[AppContext]) -> dict[str, Any]:
    return _client(ctx).version()


@tool(
    description="Show curated Docker host and storage-driver diagnostics",
    annotations=ToolAnnotations(
        read_only_hint=True, idempotent_hint=True, open_world_hint=False
    ),
)
def docker_system_info(ctx: Context[AppContext]) -> dict[str, Any]:
    info = _client(ctx).info()
    return {key: info[key] for key in _SYSTEM_INFO_KEYS if key in info}
