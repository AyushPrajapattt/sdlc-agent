# hackfront API (FastAPI). Stateless: workspaces, saved keys, investigations and sync status live in Neo4j
# (HACKFRONT_STATE=neo4j), so no disk is needed. Needs NEO4J_URI/USERNAME/PASSWORD, HACKFRONT_SECRET_KEY (encrypts
# saved keys) and, for a public host, HACKFRONT_ACCESS_TOKEN. Sync jobs run in-process: run exactly one instance.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 UV_LINK_MODE=copy
RUN pip install uv
WORKDIR /app

# dependencies first (cached layer), then the source
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH" HACKFRONT_STATE=neo4j PORT=8000
EXPOSE 8000
CMD ["sh", "-c", "uvicorn hackfront.api:app --host 0.0.0.0 --port ${PORT}"]
