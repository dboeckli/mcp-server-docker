# Upstream & fork tracking

This fork is based on
[`ckreiling/mcp-server-docker`](https://github.com/ckreiling/mcp-server-docker).
We track **both** the base repository and the most relevant community fork,
[`X1pheR/mcp-server-docker`](https://github.com/X1pheR/mcp-server-docker).

The base repository is the source of new issues and pull requests. The
`X1pheR` fork is community-maintained and already carries branch-level fixes
for several open upstream issues, so it is often faster to port its branch than
to re-implement a fix from scratch.

## Tracked sources

| Role | Repository | Why |
| --- | --- | --- |
| Base | [`ckreiling/mcp-server-docker`](https://github.com/ckreiling/mcp-server-docker) | Canonical issues, pull requests and releases |
| Reference fork | [`X1pheR/mcp-server-docker`](https://github.com/X1pheR/mcp-server-docker) | Ready-made branches for several upstream issues |
| This fork | [`dboeckli/mcp-server-docker`](https://github.com/dboeckli/mcp-server-docker) | Where accepted fixes land |

## X1pheR branch ↔ upstream issue map

Status as of 2026-11-27. Re-check before relying on it; branches may be merged,
renamed or deleted upstream.

| X1pheR branch | Upstream issue | Tracking here |
| --- | --- | --- |
| `fix/attached-run-output` | [#69](https://github.com/ckreiling/mcp-server-docker/issues/69) | [#77](https://github.com/dboeckli/mcp-server-docker/issues/77) |
| `fix/build-intermediate-cleanup` | [#68](https://github.com/ckreiling/mcp-server-docker/issues/68) | [#79](https://github.com/dboeckli/mcp-server-docker/issues/79) |
| `fix/docker-filter-none-values` | [#67](https://github.com/ckreiling/mcp-server-docker/issues/67) | Already fixed here (`0919f4b`) |
| `contribution/docker-mcp-recreate-optin-62` | [#62](https://github.com/ckreiling/mcp-server-docker/issues/62) | Not yet addressed |
| `contribution/docker-mcp-log-bounds-70` | [#70](https://github.com/ckreiling/mcp-server-docker/issues/70) | [#82](https://github.com/dboeckli/mcp-server-docker/issues/82) |
| `contribution/docker-mcp-paramiko-extra-72` | [#72](https://github.com/ckreiling/mcp-server-docker/issues/72) | Partially addressed (`paramiko` 5.x) |

## Checking for new activity

```bash
# Base repo: open issues, open pull requests and new commits on main
gh issue list --repo ckreiling/mcp-server-docker --state open --limit 100
gh pr list --repo ckreiling/mcp-server-docker --state open --limit 100
git fetch https://github.com/ckreiling/mcp-server-docker.git main
git log --oneline HEAD..FETCH_HEAD

# Reference fork: branches and how far its main is ahead of upstream
gh api repos/X1pheR/mcp-server-docker/branches --jq '.[].name'
gh api repos/ckreiling/mcp-server-docker/compare/main...X1pheR:main \
  --jq '"ahead=\(.ahead_by) behind=\(.behind_by)"'

# The diff of a specific contribution branch
gh api repos/ckreiling/mcp-server-docker/compare/main...X1pheR:fix/attached-run-output \
  --jq '.commits[].commit.message'
```

## Triage notes

- Many recent upstream issues are automated or AI-generated reports (directory
  listings, conformance sweeps, security-disclosure requests). Check whether an
  issue describes a real code change before copying it into this fork.
- Prefer porting an existing `X1pheR` branch over re-implementing the same fix;
  adapt it to this fork's renamed tools (`docker_*`) and `@tool`/`_client`
  structure.
- When a fix is ported, update the branch/issue mapping in this file and close
  the corresponding tracking issue.
