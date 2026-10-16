# hackfront API (FastAPI). Needs a long-running process + a persistent disk mounted at /data (workspaces, keys,
# investigations) + a Neo4j database reachable through NEO4J_URI. Not suitable for serverless platforms.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 UV_LINK_MODE=copy
RUN pip install uv
WORKDIR /app

# dependencies first (cached layer), then the source
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" HACKFRONT_HOME=/data PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn hackfront.api:app --host 0.0.0.0 --port ${PORT}"]
