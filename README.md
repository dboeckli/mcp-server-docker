# 🐋 Docker MCP server

An MCP server for managing Docker with natural language!

> This is the [`dboeckli` fork](https://github.com/dboeckli/mcp-server-docker) of
> [`ckreiling/mcp-server-docker`](https://github.com/ckreiling/mcp-server-docker).
> Credit for the original server belongs to Christian Kreiling and the upstream
> contributors. This fork adds the Buildx tools and related maintenance.

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

## 🍴 What this fork adds

- Buildx tools: `buildx_list`, `buildx_history`, and `buildx_logs`
- Clear tool error messages, including Docker and Buildx failures
- A published container image: `ghcr.io/dboeckli/mcp-server-docker`
- Docker/Buildx integration tests and coverage in CI
- Automated dependency updates (Dependabot and Renovate)

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
- Read-only tools (`list_*`, `fetch_container_logs`, `buildx_*`) can be
  allow-listed; write tools should stay behind `ask` or be denied.
- The Buildx tools added by this fork are meant for this setup: inspecting
  builders, build history and build logs from inside the sandbox.

This is not a sandbox boundary by itself: the host-side server still has access
to the host Docker daemon. Use the gateway's permission rules and review them.

## 🏎️ Quickstart

### Install

#### Claude Desktop

On MacOS: `~/Library/Application\ Support/Claude/claude_desktop_config.json`

On Windows: `%APPDATA%/Claude/claude_desktop_config.json`

<details>
  <summary>Install from GitHub with uv</summary>

This fork is not published to PyPI. Install it directly from the tagged GitHub
source (`v0.4.3`).

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
      "git+https://github.com/dboeckli/mcp-server-docker@v0.4.3",
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
  ghcr.io/dboeckli/mcp-server-docker:0.4.3
```

Alternatively, build the image locally:

```bash
docker build -t mcp-server-docker:0.4.3 .
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
      "ghcr.io/dboeckli/mcp-server-docker:0.4.3"
    ]
  }
}
```

Note that we mount the Docker socket as a volume; this ensures the MCP server
can connect to and control the local Docker daemon. The image does not include
the Docker CLI, so the Buildx tools only work when the server runs where the
CLI is installed.

</details>

## 📔 Resources

The server exposes resource templates rather than enumerating currently-running containers:

- `docker://containers/{container_id}/logs` (`text/plain`)
- `docker://containers/{container_id}/stats` (`application/json`)

Read either URI with a Docker container ID or name.

## 🔨 Tools

### Containers

- `list_containers`
- `create_container`
- `run_container`
- `recreate_container`
- `start_container`
- `fetch_container_logs`
- `stop_container`
- `remove_container`

### Images

- `list_images`
- `pull_image`
- `push_image`
- `build_image`
- `remove_image`
- `image_inspect`
- `image_history`

`image_inspect` replaces environment values with `<redacted>`. `image_history`
is not redacted: layer `CreatedBy` commands can contain secrets baked into the
image.

### Buildx

- `buildx_list`
- `buildx_du`
- `buildx_history`
- `buildx_logs`

These tools invoke the `docker` CLI, so the `docker` binary (with the Buildx
plugin) must be available on `PATH`. The container image built from this
repository does not include the Docker CLI, so the Buildx tools are only usable
when the server runs where the CLI is installed.

### System

- `system_df`

`system_df` uses the `docker` CLI and reports the same summary as
`docker system df`, including reclaimable space. Pass `verbose=true` for the
per-image, per-container, per-volume, and build-cache detail.

### Networks

- `list_networks`
- `create_network`
- `remove_network`

### Volumes

- `list_volumes`
- `create_volume`
- `remove_volume`

## 📝 Prompts

### 🎻 `docker_compose`

Optional: turns a project name and a container description into a `plan+apply`
loop for containers, volumes, and networks. Reusing an existing project name
lets the LLM see the current state, which is useful for cleanup.

This prompt is not required to use the server; the tools work directly without
it.

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
      "git+https://github.com/dboeckli/mcp-server-docker@v0.4.3",
      "mcp-server-docker"
    ],
    "env": {
      "DOCKER_HOST": "ssh://myusername@myhost.example.com"
    }
  }
}
```

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
