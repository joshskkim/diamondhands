# syntax=docker/dockerfile:1
# Built from the REPO ROOT context (needs both ingester/ and data/):
#   docker build -f ingester/Dockerfile -t diamond-ingester .
# A one-shot job image — run a subcommand, e.g.
#   docker compose -f compose.prod.yml run --rm ingester daily
FROM python:3.12-slim

# OpenMP runtime needed by xgboost / scikit-learn wheels.
RUN apt-get update && apt-get install -y --no-install-recommends libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# uv (installed from PyPI to avoid an external registry dependency at build time).
RUN pip install --no-cache-dir "uv>=0.5,<0.6"
ENV UV_LINK_MODE=copy
WORKDIR /app

# Resolve dependencies first (cached) using only the lockfiles.
COPY ingester/pyproject.toml ingester/uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen --no-install-project

# App code + static reference data. main.py's default --data-dir resolves to /data
# (Path(__file__).parent.parent / "data" → /app/.. /data).
COPY ingester/ /app/
COPY data/ /data/
RUN --mount=type=cache,target=/root/.cache/uv uv sync --frozen

# --no-sync: the venv is already built into the image, so skip the per-run re-sync.
ENTRYPOINT ["uv", "run", "--no-sync", "python", "main.py"]
