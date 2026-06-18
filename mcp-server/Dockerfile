# syntax=docker/dockerfile:1
# Built from the REPO ROOT context (mirrors the ingester image build):
#   docker build -f mcp-server/Dockerfile -t diamond-mcp .
# Serves the networked HTTP transport (auth + rate limiting + metrics + tracing).
FROM python:3.12-slim

# uv (from PyPI to avoid an external registry dependency at build time).
RUN pip install --no-cache-dir "uv>=0.5,<0.6"
ENV UV_LINK_MODE=copy
WORKDIR /app

# Resolve dependencies first (cached) using only the lockfiles.
COPY mcp-server/pyproject.toml mcp-server/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project

# App code, then build the project into the image's venv.
COPY mcp-server/ /app/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

# Networked transport, listening on all interfaces inside the container.
ENV MCP_TRANSPORT=http MCP_HOST=0.0.0.0 MCP_PORT=8090
EXPOSE 8090

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8090/healthz')"]

# --no-sync: the venv is already built into the image, so skip the per-run re-sync.
ENTRYPOINT ["uv", "run", "--no-sync", "diamond-mcp"]
