FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim@sha256:e5b65587bce7de595f299855d7385fe7fca39b8a74baa261ba1b7147afa78e58 AS uv

WORKDIR /app

ENV UV_COMPILE_BYTECODE=1

# Copy from the cache instead of linking since it's a mounted volume
ENV UV_LINK_MODE=copy

COPY uv.lock pyproject.toml /app/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev --no-editable --no-build

COPY ./src /app/src
COPY README.md ./README.md
COPY LICENSE LICENSE
COPY NOTICE NOTICE
# Dependencies are installed with --no-build above; this step builds only the
# local package, so it cannot use --no-build.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

FROM python:3.12.16-slim-bookworm@sha256:44cf1793efa7c7a476bb0f2cff81443f4a072c90c1cb127e2924933daa3e8c64

LABEL io.modelcontextprotocol.server.name="io.github.dboeckli/mcp-server-docker"

WORKDIR /app
 
COPY --from=uv --chown=app:app /app/.venv /app/.venv

# Ensure executables in the venv take precedence over system executables
ENV PATH="/app/.venv/bin:$PATH"

# when running the container, add --db-path and a bind mount to the host's db file
ENTRYPOINT ["mcp-server-docker"]
