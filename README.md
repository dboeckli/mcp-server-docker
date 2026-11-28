# 🐋 Docker MCP server

<!-- mcp-name: io.github.dboeckli/mcp-server-docker -->

[![CI](https://github.com/dboeckli/mcp-server-docker/actions/workflows/ci.yml/badge.svg)](https://github.com/dboeckli/mcp-server-docker/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/mcp-server-docker-dboeckli)](https://pypi.org/project/mcp-server-docker-dboeckli/)
[![ghcr.io](https://img.shields.io/badge/ghcr.io-mcp--server--docker-blue)](https://github.com/dboeckli/mcp-server-docker/pkgs/container/mcp-server-docker)
[![License: GPL-3.0-only](https://img.shields.io/github/license/dboeckli/mcp-server-docker)](LICENSE)
[![Quality Gate Status](https://sonarcloud.io/api/project_badges/measure?project=dboeckli_mcp-server-docker&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=dboeckli_mcp-server-docker)
[![Coverage](https://sonarcloud.io/api/project_badges/measure?project=dboeckli_mcp-server-docker&metric=coverage)](https://sonarcloud.io/summary/new_code?id=dboeckli_mcp-server-docker)
[![Vulnerabilities](https://sonarcloud.io/api/project_badges/measure?project=dboeckli_mcp-server-docker&metric=vulnerabilities)](https://sonarcloud.io/summary/new_code?id=dboeckli_mcp-server-docker)
[![Docker MCP Server on Glama](https://glama.ai/mcp/servers/dboeckli/mcp-server-docker/badges/score.svg)](https://glama.ai/mcp/servers/dboeckli/mcp-server-docker)
[![MCP Registry](https://img.shields.io/badge/MCP_Registry-listed-blue)](https://registry.modelcontextprotocol.io/v0.1/servers?search=io.github.dboeckli/mcp-server-docker)

An MCP server for managing Docker with natural language — maintained, with
Buildx tooling and bounded, LLM-friendly output.

```bash
uvx --from mcp-server-docker-dboeckli mcp-server-docker
```

> **Maintenance status:** the upstream project
> [`ckreiling/mcp-server-docker`](https://github.com/ckreiling/mcp-server-docker)
> last released `v0.3.0` and is effectively unmaintained. This repository is its
> maintained continuation: it keeps the upstream Docker MCP surface and is
> released independently as `mcp-server-docker-dboeckli` (PyPI) and
> `ghcr.io/dboeckli/mcp-server-docker` (GHCR).
>
> Credit for the original server belongs to Christian Kreiling and the upstream
> contributors. Maintained by [dboeckli](https://github.com/dboeckli); not
> affiliated with or endorsed by the upstream maintainer, Docker, Inc., or the
> Model Context Protocol project. Fixes are maintained here only and are not
> contributed back upstream.

See the [Quickstart](#-quickstart) below for Claude Desktop, container and
source setups.

## 🧭 Why this repository exists

This repository keeps the upstream Docker MCP surface and adds what is needed to
run it from agent sandboxes and day-to-day LLM clients. It is based on upstream
`main` at `57a7df2` (v0.3.0) and is released independently as
`mcp-server-docker-dboeckli` (PyPI) and
`ghcr.io/dboeckli/mcp-server-docker` (GHCR).

The differences that matter in practice:

- **Buildx tooling:** builders, build history, cache usage, inspection and build logs.
- **Bounded, LLM-friendly output:** compact `summary` listings plus capped log
  and attached-run output with `truncated`/`bytes` metadata.
- **More read-only tools:** container health, processes, stats, events, disk
  usage, version, system info and a redacted daemon health probe.
- **Safety modes** (`--read-only`, `--disable-destructive`) for gateway
  allow-listing.
- **Docker Desktop correctness:** label filters in the CLI map form and unset
  filter fields omitted instead of sent as `null`.
- **Packaging:** PyPI package, GHCR image and an independent release history.

This is an independent downstream project, not an upstream contribution channel:
fixes are maintained here only and are not contributed back upstream. See
[docs/upstream-tracking.md](docs/upstream-tracking.md) for the repositories we
monitor and [CHANGELOG.md](CHANGELOG.md) for release history.

## 🪩 What can it do?

- 🚀 Compose containers with natural language
- 🔍 Introspect & debug running containers
- 📀 Manage persistent data with Docker volumes

## ❓ Who is this for?

- Server administrators: connect to remote Docker engines for e.g. managing a
  public-facing website.
- Tinkerers: run containers locally and experiment with open-source apps
  supporting Docker.
- AI enthusiasts: push the limits of what an LLM is capable of!
- Docker sandbox users: expose the host Docker daemon and Buildx to a sandbox
  through an MCP gateway without mounting the Docker socket.

## 🍴 What this repository adds

- Buildx tools: `docker_buildx_list`, `docker_buildx_history`, and
  `docker_buildx_logs`
- Clear tool error messages, including Docker and Buildx failures
- A published container image: `ghcr.io/dboeckli/mcp-server-docker`
- A published PyPI package: `mcp-server-docker-dboeckli`
- Docker/Buildx integration tests and coverage in CI
- Automated dependency updates (Dependabot and Renovate)

## 🔭 Upstream tracking

We track the upstream base repository and, in addition, the `X1pheR` community
fork, which carries ready branches for several open upstream issues. Monitored
sources, the branch-to-issue map and the commands to check for new activity are
documented in [docs/upstream-tracking.md](docs/upstream-tracking.md).

## 🧱 Use case: Docker sandbox

This server was originally designed for direct Docker management from an MCP
client. It can also serve as the host-side bridge for a **Docker sandbox** (for
example
[opencode-sandbox-kit](https://codeberg.org/dboeckli/opencode-sandbox-kit)):

- The sandbox keeps its own isolated Docker daemon; the host Docker socket is
  **not** mounted into it and port `2375` is not exposed.
- This server runs on the host and is registered with an MCP gateway (for
  example the `sbx` MCP gateway).
- The sandbox reaches the gateway over MCP and only sees the tools the gateway
  allows.
- Read-only tools (`docker_list_*`, `docker_fetch_container_logs`,
  `docker_buildx_*`) can be allow-listed; write tools should stay behind `ask`
  or be denied.
- The Buildx tools added by this repository are meant for this setup: inspecting
  builders, build history and build logs from inside the sandbox.

This is not a sandbox boundary by itself: the host-side server still has access
to the host Docker daemon. Use the gateway's permission rules and review them.

## 🏎️ Quickstart

### Install

#### Claude Desktop

On MacOS: `~/Library/Application\ Support/Claude/claude_desktop_config.json`

On Windows: `%APPDATA%/Claude/claude_desktop_config.json`

<details>
  <summary>Install from PyPI with uv (recommended)</summary>

The package is published to PyPI as
[`mcp-server-docker-dboeckli`](https://pypi.org/project/mcp-server-docker-dboeckli/).
That is fast to start (a wheel download, no clone and no build) and needs no
Git.

> The PyPI name **`mcp-server-docker`** belongs to the
> [upstream project](https://github.com/ckreiling/mcp-server-docker) and stops at
> `0.3.0`. It does not contain the Buildx tools of this repository.

If you don't have `uv` installed, follow the installation instructions for your
system:
[link](https://docs.astral.sh/uv/getting-started/installation/#installation-methods)

Then add the following to your MCP servers file:

```
"mcpServers": {
  "mcp-server-docker": {
    "command": "uvx",
    "args": [
      "--from",
      "mcp-server-docker-dboeckli==0.13.0",
      "mcp-server-docker"
    ]
  }
}
```

</details>

<details>
  <summary>Install from a GitHub release wheel</summary>

Every release attaches the built wheel and sdist. This works without PyPI and
without cloning the repository:

```bash
uvx --from https://github.com/dboeckli/mcp-server-docker/releases/download/v0.13.0/mcp_server_docker_dboeckli-0.13.0-py3-none-any.whl \
  mcp-server-docker
```

</details>

<details>
  <summary>Install from GitHub source with uv</summary>

Pins the Git tag and builds from source on first start. Use this only when you
want to run unreleased commits; it needs Git and is slower to start than the
PyPI or wheel install.

```
"mcpServers": {
  "mcp-server-docker": {
    "command": "uvx",
    "args": [
      "--from",
      "git+https://github.com/dboeckli/mcp-server-docker@v0.13.0",
      "mcp-server-docker"
    ]
  }
}
```

</details>

<details>
  <summary>Install with Docker</summary>

Purely for convenience, the server can run in a Docker container. A prebuilt
image is published to GHCR:

```bash
docker run -i --rm \
  -v /var/run/docker.sock:/var/run/docker.sock \
  ghcr.io/dboeckli/mcp-server-docker:0.13.0
```

Alternatively, build the image locally:

```bash
docker build -t mcp-server-docker:0.13.0 .
```

And then add the following to your MCP servers file:

```
"mcpServers": {
  "mcp-server-docker": {
    "command": "docker",
    "args": [
      "run",
      "-i",
      "--rm",
      "-v",
      "/var/run/docker.sock:/var/run/docker.sock",
      "ghcr.io/dboeckli/mcp-server-docker:0.13.0"
    ]
  }
}
```

Note that we mount the Docker socket as a volume; this ensures the MCP server
can connect to and control the local Docker daemon. The image does not include
the Docker CLI, so the Buildx tools only work when the server runs where the
CLI is installed.

</details>

## 🔏 Verifying the image

Release tags (`v*`) publish `linux/amd64` and `linux/arm64` images, plus SLSA
provenance (`mode=max`) and an SPDX SBOM as OCI attestations per platform. Pulling the image is unchanged; inspect the
attestations with:

```bash
docker buildx imagetools inspect ghcr.io/dboeckli/mcp-server-docker:0.13.0 \
  --format '{{json .Provenance}}'

docker buildx imagetools inspect ghcr.io/dboeckli/mcp-server-docker:0.13.0 \
  --format '{{json .SBOM}}'
```

The provenance records the source repository, the commit and the build
arguments; the SBOM lists the packages in the image. Narrow the output with
`.Provenance.SLSA` or `.SBOM.SPDX`, for example
`--format '{{json .SBOM.SPDX}}'`. Branch and pull-request builds are not
attested, so only release tags carry these statements.

Attestations prove what was built, not what the container may do: the image
still mounts the host Docker socket and is as privileged as the daemon it talks
to. Keep the sandbox/gateway boundary in place.

## 📔 Resources

The server exposes resource templates rather than enumerating currently-running containers:

- `docker://containers/{container_id}/logs` (`text/plain`)
- `docker://containers/{container_id}/stats` (`application/json`)

Read either URI with a Docker container ID or name.

## 🔨 Tools

> **Breaking in 0.8.0:** every tool name is prefixed with `docker_` so the flat
> MCP gateway namespace stays collision-free (for example `list_containers` is
> now `docker_list_containers`). Update gateway allow-lists and prompts that
> name tools directly. Resource URIs and the `docker_compose` prompt are
> unchanged.

### Containers

- `docker_list_containers`
- `docker_create_container`
- `docker_run_container`
- `docker_recreate_container`
- `docker_start_container`
- `docker_fetch_container_logs`
- `docker_stop_container`
- `docker_remove_container`
- `docker_container_inspect`
- `docker_container_health`
- `docker_container_processes`
- `docker_container_stats`
- `docker_container_exec`
- `docker_container_prune`

`docker_container_inspect` redacts environment values like
`docker_image_inspect`. `docker_container_health` returns a compact summary
instead of the full inspect
payload: state, health status with the last health log entry, restart count,
exit code, `OOMKilled`, start/finish timestamps, image and command. It builds a
fresh response, so no environment value is included.
`docker_container_processes` is the equivalent of `docker top`.
`docker_container_stats` returns a one-shot CPU, memory, network and block-IO
snapshot (`stream=false`), so it never blocks a tool call; the
`docker://containers/{container_id}/stats`
resource stays available for clients that read resources.

`docker_container_exec` runs an argv command in a running container and returns
`exit_code`, `output`, `truncated` and `bytes`. `command` is a JSON array, so
there is no shell interpolation; `workdir` and `env` map to the exec API and no
TTY is allocated. Output is capped at the last 20 KiB, `timeout_seconds`
defaults to 30 (clamped to 1-300) and a timeout is reported as an error; the
process may keep running in the container. A non-zero exit code is returned as
data, not as a tool error. This is a write tool: it is absent under
`--read-only`, stays available under `--disable-destructive`, and is
host-root-equivalent like the other write tools.

`docker_run_container` with `detach=false` returns `mode: "attached"`, the
decoded `output`, the original byte count (`bytes`) and a `truncated` flag.
Only the last 20 KiB of raw output are returned, so an attached process cannot
flood the client with unbounded text. `ports` accepts JSON arrays too, e.g.
`{"80/tcp": 8080}`, `{"80/tcp": [8080, 8081]}` for several host ports, or
`{"80/tcp": ["127.0.0.1", 8080]}` for a host IP and port.

`docker_fetch_container_logs` returns at most the last 20 KiB of raw log bytes,
split on newlines into `logs`, together with `truncated` and the original byte
count (`bytes`); invalid UTF-8 is replaced.

`docker_recreate_container` keeps its original stop/remove/run behaviour by
default. With `preserve_configuration=true` it rebuilds the container from its
inspected configuration instead: environment, mounts/volume identity, networks,
ports, labels, healthcheck and restart policy are preserved, the replacement
image is checked before anything is removed, and the original configuration is
restored if creating the replacement fails. In that mode pass only
`container_id`/`name` and optionally `image` (omitted `image` reuses the current
one); explicit overrides are rejected.

Every list tool returns a single JSON array. `docker_list_containers`,
`docker_list_images` and `docker_list_volumes` accept `format`: the default
`summary` returns a compact `docker ps`-style row (no health-check logs, nested
image object, labels or digests), while `full` returns the inspect-level object
with each health-check log entry capped at 500 characters. `docker_list_containers`
mirrors `docker ps`: without filters it returns the same containers as the CLI,
and a `label` filter is sent in the CLI's map form. That matters on Docker Desktop
hosts with the Kubernetes integration: the engine hides Kubernetes containers
from unfiltered listings but reveals them for a `label` filter, so
`docker_list_containers {"all": true, "filters": {"label":
["io.kubernetes.pod.namespace=kube-system"]}}` returns them just like
`docker ps --filter label=...`. Unset filter fields are not forwarded.

### Images

- `docker_list_images`
- `docker_pull_image`
- `docker_push_image`
- `docker_build_image`
- `docker_remove_image`
- `docker_image_inspect`
- `docker_image_history`
- `docker_image_prune`

`docker_image_inspect` replaces environment values with `<redacted>`.
`docker_image_history` is not redacted: layer `CreatedBy` commands can contain
secrets baked into the image.

### Buildx

- `docker_buildx_build`
- `docker_buildx_list`
- `docker_buildx_du`
- `docker_buildx_inspect`
- `docker_buildx_history`
- `docker_buildx_logs`
- `docker_buildx_prune`

These tools invoke the `docker` CLI, so the `docker` binary (with the Buildx
plugin) must be available on `PATH`. The container image built from this
repository does not include the Docker CLI, so the Buildx tools are only usable
when the server runs where the CLI is installed.

CLI output is decoded as UTF-8 with malformed bytes replaced by `�` (U+FFFD),
independent of the host code page, so build logs with non-UTF-8 bytes cannot
crash a tool on Windows.

`docker_buildx_logs` accepts `progress="plain"` and `progress="rawjson"`. The
`tty` mode needs a terminal, which a stdio MCP server never has, so the tool
rejects it with an explanatory error instead of calling the CLI.

`docker_buildx_build` starts a Buildx build and returns the build reference
from `buildx.build.ref` plus the bounded output tail. Pass that `ref` unchanged
to `docker_buildx_logs` to inspect the build. `context` is a path or URL;
`tags`, `build_args`, `target`, `builder`, `cache_from`, `cache_to` and
`platform` map to the corresponding CLI flags, and `no_cache` disables the
cache. `push` and `load` are mutually exclusive; `push` requires at least one
tag and is never implied by `load`. Builds are bounded by `timeout_seconds`
(default 600, clamped to 1-3600); a timeout or non-zero exit raises an error
that includes the last 20 KiB of output. It is destructive (expensive), so it
is absent under `--disable-destructive` and `--read-only`.

`docker_buildx_prune` prunes the requested builder or every builder returned by
`docker buildx ls`, always with `--force`. It reports the reclaimed space and
the deleted cache record IDs per builder and adds `--all` unless disabled. A
failing builder yields an `error` entry while the remaining builders are still
pruned. It is destructive, so it is absent under `--disable-destructive` and
`--read-only`.

### System

- `docker_system_df`
- `docker_system_prune`
- `docker_version`
- `docker_system_info`
- `docker_status`

`docker_status` is the health probe for gateways and orchestrators: it checks
the daemon with a 2-second timeout and always answers instead of raising.
`status` is `ok` when the daemon responded and `degraded` when the server is
alive but the daemon is not. The payload includes the MCP server name/version
(useful when a gateway masks the `initialize` `serverInfo`), the Docker engine
and API versions, the measured latency and a UTC timestamp. Daemon errors are
redacted: socket and certificate paths, URL credentials and `DOCKER_*`
environment values are removed. The tool takes no arguments and is available in
read-only mode.

`docker_system_df` uses the `docker` CLI and reports the same summary as
`docker system df`, including reclaimable space. Pass `verbose=true` for the
per-image, per-container, per-volume, and build-cache detail.

`docker_system_prune` reclaims stopped containers, unused networks, unused
images and build cache in one call and reports `space_reclaimed` plus the
deleted IDs per category. `all` defaults to `true` (unused images, not just
dangling ones); `volumes` defaults to `false`, so anonymous volumes are only
pruned when explicitly requested. `docker_container_prune`,
`docker_image_prune` and `docker_volume_prune` expose the individual
operations. All four use the Docker SDK and return `deleted` and
`space_reclaimed`. They are destructive, so they are absent under
`--disable-destructive` and `--read-only`.

`docker_system_df` and `docker_system_info` take their numbers straight from
the engine, while `docker_list_containers` mirrors `docker ps`. Some engines
(Docker Desktop's Kubernetes integration, for example) hide containers from
unfiltered container listings while still counting them in `/info` and
`/system/df`, so `system_info.ContainersRunning` can exceed the number of
containers returned without filters. Pass a `label` filter to
`docker_list_containers` to list them.

### Events

- `docker_events_list`

`docker_events_list` reports recent Docker events (`die`, `oom`, `unhealthy`,
restart loops) for a window that always ends *now*, so a call can never wait
for future
events:

- `window_seconds` (default `900`, clamped to `1..86400`) is how far back to
  look. There is no `until` parameter on purpose. The window end is rounded up
  to the next full second, so events from the current second are included.
- `limit` (default `100`, clamped to `1..1000`) keeps the **newest** events and
  sets `truncated=true` when the window holds more.
- `filters` accepts `type`, `event`, `container`, `image` and `label`, each a
  list, and maps them to repeated `--filter key=value` arguments.
- The CLI call itself is bounded too: if `docker events` does not return in
  time, the events collected so far are returned with `truncated=true` and
  `truncated_reason="timeout"` instead of a generic timeout error.

Like the Buildx tools, `docker_events_list` invokes the `docker` CLI and needs
it on `PATH`.

### Networks

- `docker_list_networks`
- `docker_network_inspect`
- `docker_create_network`
- `docker_remove_network`

`docker_network_inspect` returns the full network attributes, including driver,
IPAM configuration and connected containers.

### Volumes

- `docker_list_volumes`
- `docker_volume_inspect`
- `docker_create_volume`
- `docker_remove_volume`
- `docker_volume_prune`

`docker_volume_inspect` returns the full volume attributes, including driver,
mountpoint, labels and options.

Both inspect tools apply the same environment redaction as
`docker_container_inspect` (`<redacted>`), so the reading posture stays uniform
even if the daemon adds a `Config.Env` section.

## 📝 Prompts

### 🎻 `docker_compose`

Optional: turns a project name and a container description into a `plan+apply`
loop for containers, volumes, and networks. Reusing an existing project name
lets the LLM see the current state, which is useful for cleanup.

This prompt is not required to use the server; the tools work directly without
it.

## 🔒 Safety modes

Three modes decide which tools are registered. A filtered tool is absent from
`tools/list`, and calling it returns `Unknown tool`.

| Mode | Flag / env | Tools |
| --- | --- | --- |
| Default | – | 44 |
| No destructive | `--disable-destructive` / `MCP_SERVER_DOCKER_DISABLE_DESTRUCTIVE=1` | 33 |
| Read-only | `--read-only` / `MCP_SERVER_DOCKER_READ_ONLY=1` | 23 |

- **No destructive** removes the eleven tools annotated with
  `destructiveHint=true` (`docker_remove_container`, `docker_remove_image`,
  `docker_remove_network`, `docker_remove_volume`,
  `docker_recreate_container`, `docker_container_prune`,
  `docker_image_prune`, `docker_volume_prune`, `docker_system_prune`,
  `docker_buildx_prune`, `docker_buildx_build`). Creating, pulling, starting
  and stopping containers still works, as does `docker_container_exec`
  (annotated non-destructive). `--no-destructive` and
  `MCP_SERVER_DOCKER_NO_DESTRUCTIVE` are accepted as synonyms.
- **Read-only** exposes only tools annotated with `readOnlyHint=true`: all
  `docker_list_*`, log, stats, inspect, `docker_container_health`,
  `docker_events_list`, `docker_status`, disk usage and the Buildx inspection
  tools.
- Read-only is the stricter mode and wins when both are set.
- The container log/stats resources and the `docker_compose` prompt stay
  available in every mode.

Per-tool overrides on top of the modes:

- `--enable-tools docker_version,docker_system_info` (repeatable,
  `MCP_SERVER_DOCKER_ENABLE_TOOLS`) registers the named tools regardless of the
  mode above.
- `--disable-tools docker_stop_container` (repeatable,
  `MCP_SERVER_DOCKER_DISABLE_TOOLS`) removes the named tools, unless the same
  tool is also enabled.
- Naming a tool in both lists aborts startup with an error.

Example with `uvx`:

```json
"args": [
  "--from",
  "git+https://github.com/dboeckli/mcp-server-docker@v0.13.0",
  "mcp-server-docker",
  "--disable-destructive"
]
```

Or with the environment variables:

```json
"env": {
  "MCP_SERVER_DOCKER_DISABLE_DESTRUCTIVE": "1",
  "MCP_SERVER_DOCKER_DISABLE_TOOLS": "docker_stop_container"
}
```

For the sbx MCP gateway, append the flag to the comma-separated `--args` list,
e.g. `sbx mcp add docker --args "--from,...,mcp-server-docker,--disable-destructive"`.

These modes are best-effort guardrails, not a sandbox boundary. The process
still has host Docker access; keep gateway policy and sandbox isolation in place.

## 🚧 Disclaimers

### Sensitive Data

**DO NOT CONFIGURE CONTAINERS WITH SENSITIVE DATA.** This includes API keys,
database passwords, etc.

Any sensitive data exchanged with the LLM is inherently compromised, unless the
LLM is running on your local machine.

If you are interested in securely passing secrets to containers, file an issue
on this repository with your use-case.

### Reviewing Created Containers

Be careful to review the containers that the LLM creates. Docker is not a secure
sandbox, and therefore the MCP server can potentially impact the host machine
through Docker.

For safety reasons, this MCP server doesn't support sensitive Docker options
like `--privileged` or `--cap-add/--cap-drop`. If these features are of interest
to you, file an issue on this repository with your use-case.

## 🛠️ Configuration

This server uses the Python Docker SDK's `from_env` method. For configuration
details, see
[the documentation](https://docker-py.readthedocs.io/en/stable/client.html#docker.client.from_env).

### Connect to Docker over SSH

This MCP server can connect to a remote Docker daemon over SSH.

Simply set a `ssh://` host URL in the MCP server definition:

```
"mcpServers": {
  "mcp-server-docker": {
    "command": "uvx",
    "args": [
      "--from",
      "git+https://github.com/dboeckli/mcp-server-docker@v0.13.0",
      "mcp-server-docker"
    ],
    "env": {
      "DOCKER_HOST": "ssh://myusername@myhost.example.com"
    }
  }
}
```

## 📜 Changelog

Release notes and the history of notable changes live in
[CHANGELOG.md](CHANGELOG.md).

## 💻 Development

Prefer using Devbox to configure your development environment. The server uses
MCP Python SDK v2's high-level `MCPServer` API and can be inspected directly:

```bash
uv sync --all-groups
uv run mcp dev src/mcp_server_docker/server.py:app
# or: npx @modelcontextprotocol/inspector uv run mcp-server-docker
```

Run the hermetic test and lint suite without a Docker daemon:

```bash
uv run pytest
uv run pytest --cov=mcp_server_docker --cov-report=term-missing
uv run ruff format --check src tests
uv run ruff check src tests
```

CI also writes `target/reports/coverage.xml` and `target/reports/junit.xml`
and runs SonarCloud analysis when the `SONAR_TOKEN` repository secret is
configured.

Run the Docker integration tests (requires Docker and Buildx):

```bash
uv run pytest -o addopts= -m integration
```

See the `devbox.json` for helpful development commands.

After setting up devbox you can configure your Claude MCP config to use it:

```json
{
  "mcpServers": {
    "docker": {
      "command": "/path/to/repo/.devbox/nix/profile/default/bin/uv",
      "args": [
        "--directory",
        "/path/to/repo/",
        "run",
        "mcp-server-docker"
      ]
    }
  }
}
```

## 📄 License

This project is distributed under the **GNU General Public License v3.0**
(GPL-3.0-only); see [LICENSE](LICENSE).

It is a modified version of
[`ckreiling/mcp-server-docker`](https://github.com/ckreiling/mcp-server-docker).
Upstream copyright and authorship remain with Christian Kreiling and the
upstream contributors. Modifications in this repository are maintained by
[dboeckli](https://github.com/dboeckli) under the same license. See
[NOTICE](NOTICE) and [CHANGELOG.md](CHANGELOG.md) for the recorded changes.

This repository is not affiliated with or endorsed by the upstream maintainer,
Docker, Inc., or the Model Context Protocol project.
