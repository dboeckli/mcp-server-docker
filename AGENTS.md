# AGENTS.md

## What this repo is

- Standalone continuation of
  [`ckreiling/mcp-server-docker`](https://github.com/ckreiling/mcp-server-docker),
  detached from its fork network. Fixes are maintained here only and are **not**
  contributed upstream. Monitored
  repos/branches and the issue map are in `docs/upstream-tracking.md` (base
  `ckreiling`, reference fork
  [`X1pheR/mcp-server-docker`](https://github.com/X1pheR/mcp-server-docker)).
- Single stdio MCP server for Docker. Entry point is `mcp_server_docker:main`,
  which calls `server.app.run()`. Python 3.12, `uv`, docker SDK `>=7.1`, `mcp` 2.x.
- Every MCP tool is named `docker_*`; resource URIs and the `docker_compose`
  prompt are not prefixed.
- GPL-3.0-only. Keep `LICENSE`, `NOTICE`, and attribution intact.

## Commands

```bash
uv sync --all-groups
uv run mcp-server-docker                  # stdio server; not `python -m mcp_server_docker`
uv run pytest                             # integration tests excluded via pyproject addopts
uv run pytest tests/test_server.py::test_name -q
uv run pytest --cov=mcp_server_docker --cov-report=term-missing --cov-fail-under=90
uv run pytest -o addopts= -m integration  # requires Docker + Buildx
uv run ruff format --check src tests
uv run ruff check src tests
uv build
```

- `devbox run prettier-check` covers root `*.json`/`*.md`; `devbox run
  pyproject-check` validates `pyproject.toml` with taplo.
- If `uv sync` cannot create `.venv` (workspace mount without symlinks), set
  `UV_PROJECT_ENVIRONMENT=/tmp/<name>` for sync/run commands.

## Architecture

- `src/mcp_server_docker/server.py` is the whole server: `@tool` registrations,
  prompt, resources and helpers. `output_schemas.py` serializes Docker models,
  `settings.py` implements the safety modes (read-only, no-destructive, per-tool
  enable/disable lists); `redaction.py` redacts `Config.Env`.
- Settings are read at **import time** and tools are registered (or omitted) then.
  A safety mode removes tools entirely (they are not registered). To test
  another mode, spawn a new process.
- Tools get the client via `_client(ctx)`; the lifespan opens `docker.from_env()`.
- List-returning tools return a Python list; the `@tool` wrapper emits one JSON
  array text block plus `structured_content={"result": [...]}`. Direct Python
  callers get the plain return value.
- Read-only tools must set `ToolAnnotations(read_only_hint=True, ...)` or they
  disappear under `--read-only`. Destructive tools must set
  `destructive_hint=True` or `--disable-destructive` keeps them.
- `docker_to_dict(obj, overrides=None, format="summary"|"full")`: list tools
  default to `summary`, single-object tools to `full`. `full` caps each
  `Health.Log` entry at 500 characters.
- Ports arrive as JSON arrays; run them through `_normalize_ports()` before the
  Docker SDK (it restores the `(host_ip, host_port)` tuple).
- Inspect tools must use `redact_env()`; never return raw `Config.Env`.
- `docker_run_container(detach=False)` returns `{mode, output, truncated, bytes}`.
  Log and attached-run text is capped at the last 20 KiB with UTF-8 replacement.
- `docker_recreate_container` keeps legacy stop/remove/run by default.
  `preserve_configuration=true` uses inspected config, preflights the image,
  rolls back on failure, keeps running state, and rejects explicit overrides.

## Tests

- `tests/test_server.py` uses a fake Docker client and monkeypatches
  `server_module.docker_to_dict`; extend that stub's signature when new kwargs
  are passed (for example `format=`).
- `tests/test_output_schemas.py` exercises the real serializers with real docker
  models; `tests/test_recreate.py` uses `Mock(spec=Container)`.
- `tests/test_settings.py` covers the safety-mode gating.
- Tool counts are asserted in tests (36 total, 22 read-only, 31 without
  destructive tools). Update them when adding/removing tools; also update
  `README.md` tool docs.
- The `production_stdio` tests spawn `uv run mcp-server-docker`; they need a
  working project venv (or `UV_PROJECT_ENVIRONMENT`).
- After changing `_version.py`, refresh editable metadata or `test_version`
  fails: `uv pip install --force-reinstall --no-deps -e .`.
- Coverage gate is 90%.

## CI, Sonar and releases

- Required PR checks: `Test & lint`, `Integration tests`, `Docker image`.
  `main` requires 1 approving review and linear history (squash/rebase only);
  direct pushes are blocked. The owner bypass exists; do not use it unless asked.
- CI installs with `uv sync --all-groups --locked --no-build` and runs with
  `uv run --locked --no-build ...`. Keep these flags (Sonar S8541/S8544).
- Pin every GitHub Action to a full commit SHA with a `# vX.Y.Z` comment
  (Sonar S7637).
- Dockerfile: the dependency-only sync uses `--no-build`; the project-install
  sync must **not** use `--no-build` (uv cannot install the workspace package
  without building it).
- SonarCloud project
  [`dboeckli_mcp-server-docker`](https://sonarcloud.io/project/overview?id=dboeckli_mcp-server-docker)
  (org `dboeckli`), config in `sonar-project.properties`, repo secret
  `SONAR_TOKEN`. Automatic Analysis must stay **off**.
- CI writes `target/reports/coverage.xml` and `target/reports/junit.xml`, uploads
  the `test-reports` artifact, and skips the Sonar scan when `SONAR_TOKEN` is
  missing, on fork PRs and on tag pushes. The quality gate is **not** enforced by
  CI; check Sonar separately.
- Tag builds publish SLSA provenance (`mode=max`) and an SPDX SBOM as OCI
  attestations; `README.md` documents `docker buildx imagetools inspect`. Keep
  them enabled when changing the image job.
- Intentionally open Sonar items: Dockerfile root user (`docker:S6471`),
  14-parameter `docker_recreate_container` (`python:S107`), recreate cognitive
  complexity (`python:S3776`).

### Release

- Version lives only in `src/mcp_server_docker/_version.py`; the release workflow
  rejects a tag that does not match it. `server.json` (official MCP Registry) is
  checked against it by `tests/test_version.py`.
- Steps: bump `_version.py` and the `server.json` version/tag; update every
  version pin in README install snippets; add a CHANGELOG entry; merge; then tag
  `vX.Y.Z` and push the tag.
- A `v*` tag triggers both workflows: `ci.yml` publishes
  `ghcr.io/dboeckli/mcp-server-docker:X.Y.Z`; `release.yml` tests, builds
  wheel/sdist, publishes PyPI `mcp-server-docker-dboeckli`, and creates the
  GitHub release. Update the release body from `CHANGELOG.md` if needed.
- `.github/workflows/registry-publish.yml` publishes `server.json` after both
  tag workflows succeeded: it waits for the other run, skips versions already in
  the registry, and pins the `mcp-publisher` release and its SHA-256. Auth is
  `mcp-publisher login github-oidc` (namespace `io.github.dboeckli`).
  `workflow_run` only takes effect once the file is on `main`.
- Do not tag before the version bump is on `main`.

## Workflow

- Use a `feature/<issue>-<short-text>` branch; never commit or push without
  explicit approval. Before a push, write `target/review/changes.patch`
  (`git diff <base>`) and open it in IntelliJ.
- This is a downstream project: do not open upstream PRs or push to `ckreiling`;
  keep `docs/upstream-tracking.md` current when addressing a tracked issue.
