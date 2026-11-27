# Changelog

Notable changes in this fork. Older releases are documented on
[GitHub Releases](https://github.com/dboeckli/mcp-server-docker/releases).

## [Unreleased]

### Added

- `--disable-destructive` (alias `--no-destructive`, env
  `MCP_SERVER_DOCKER_DISABLE_DESTRUCTIVE` / `MCP_SERVER_DOCKER_NO_DESTRUCTIVE`)
  registers every tool except the five annotated with `destructiveHint=true`, so
  an agent can create, pull, start and stop without being able to remove or
  recreate resources. `--read-only` stays the stricter mode and wins.
- `--enable-tools` and `--disable-tools` (repeatable or comma-separated, with
  `MCP_SERVER_DOCKER_ENABLE_TOOLS` / `MCP_SERVER_DOCKER_DISABLE_TOOLS`) override
  the modes per tool name; naming a tool in both lists aborts startup.
- `v*` tag builds publish SLSA provenance (`mode=max`) and an SPDX SBOM as OCI
  attestations for the GHCR image; the README explains how to inspect them.

- `registry-publish.yml` publishes `server.json` to the official MCP Registry
  once both tag workflows succeeded, replacing the manual `mcp-publisher` step.

## [0.11.0] - 2026-11-27

### Added

- The server starts even when no Docker daemon is reachable: the client falls
  back to the SDK's default API version, so `initialize` and `tools/list`
  succeed and tool calls return a clear error instead of the process failing at
  startup. This lets MCP directories and gateways enumerate the tools before a
  daemon is available.

### Documentation and metadata

- The repository is reported as a standalone project (detached from the upstream
  fork network on 2026-11-27), with a maintenance-status section, status badges
  and repository topics; `AGENTS.md` and `docs/upstream-tracking.md` use
  standalone wording.
- `glama.json` carries the full server metadata used by MCP directory listings.
- The README contains the `mcp-name` token used by the official MCP Registry to
  verify ownership of the PyPI package.
- `server.json` carries the official MCP Registry metadata, and the image label
  `io.modelcontextprotocol.server.name` lets the registry verify the GHCR image
  as well.

### Packaging

- PyPI package `mcp-server-docker-dboeckli==0.11.0`
- Container image `ghcr.io/dboeckli/mcp-server-docker:0.11.0`
- MCP Registry entry `io.github.dboeckli/mcp-server-docker`

## [0.10.0] - 2026-11-27

### Added

- `docker_recreate_container` accepts `preserve_configuration=true`: it rebuilds
  the container from its inspected configuration (environment, mounts/volume
  identity, networks, ports, labels, healthcheck, restart policy), checks the
  replacement image before stopping anything, restores the original
  configuration if replacement creation fails, and keeps the previous running
  state. The default stop/remove/run behaviour is unchanged.

### Documentation and metadata

- Added `NOTICE`, a README License section, the "Why this fork exists" rationale
  and an explicit independent-maintainer/affiliation disclaimer.
- `pyproject.toml` records the fork maintainer and the GPLv3 classifier;
  `glama.json` names the fork maintainer; the image ships `NOTICE`.
- Added `AGENTS.md` and `docs/upstream-tracking.md` for repository guidance and
  upstream/reference-fork tracking.

### Tooling

- CI runs SonarCloud analysis with coverage and JUnit reports in
  `target/reports/`, uploads the `test-reports` artifact and keeps the 90 %
  coverage gate.
- All GitHub Actions are pinned by full commit SHA; CI uses `uv sync` and
  `uv run` with `--locked --no-build`.
- Addressed the safe SonarCloud findings (uv flags, `dict.fromkeys`, a shared
  label-filter description, an unused parameter and split test assertions)
  without behaviour changes.

### Packaging

- PyPI package `mcp-server-docker-dboeckli==0.10.0`
- Container image `ghcr.io/dboeckli/mcp-server-docker:0.10.0`

## [0.9.0] - 2026-11-27

### Breaking

- `docker_list_containers`, `docker_list_images` and `docker_list_volumes` now
  default to `format="summary"`, a compact `docker ps`-style row without
  health-check logs, the nested image object, labels or digests. Pass
  `format="full"` for the previous inspect-level rows.
- `docker_run_container` with `detach=false` now returns
  `{mode: "attached", output, truncated, bytes}`. Previously this path passed
  the Docker SDK log bytes to the container serializer and failed.

### Added

- `format: "summary" | "full"` on the list tools (upstream #66). `full` caps
  each `Health.Log` entry at 500 characters, so even a full listing is bounded.
- Attached `run_container` output and `docker_fetch_container_logs` are bounded
  to the last 20 KiB and report `truncated` plus the original byte count
  (upstream #69, #70); invalid UTF-8 is replaced.
- `ports` accepts JSON arrays for the `(host_ip, host_port)` form, and every
  array in the tool input schemas declares `items` (upstream #46).
- `docs/upstream-tracking.md` tracks the upstream base repository and the
  `X1pheR` reference fork, including branch-to-issue mappings.

### Fixed

- `docker_build_image` passes `rm=True` and `forcerm=True`, so failed or
  repeated builds no longer leave intermediate containers behind (upstream #68).
- Container label filters are sent in the Docker CLI map form, which also
  reveals Kubernetes containers on Docker Desktop.
- Unset list-filter fields are no longer forwarded to the engine as `null`.

### Packaging

- PyPI package `mcp-server-docker-dboeckli==0.9.0`
- Container image `ghcr.io/dboeckli/mcp-server-docker:0.9.0`
