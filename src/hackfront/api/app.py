"""FastAPI app: routers only (docs/workbench-api.md). Errors to clients are safe messages only."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from hackfront import config

config.load_env()
# The Next.js UI (web/) runs on :3000 and proxies /api/* here; its origin is the only other one trusted.
ALLOWED_ORIGINS = set(filter(None, os.environ.get(
    "HACKFRONT_ORIGINS", "http://localhost:3000,http://127.0.0.1:3000").split(",")))
app = FastAPI(title="hackfront", docs_url=None, redoc_url=None)


@app.middleware("http")
async def same_origin_only(request, call_next):
    """CSRF guard: a browser page on another origin must not drive state-changing routes."""
    origin = request.headers.get("origin")
    if (request.method not in ("GET", "HEAD") and origin
            and urlsplit(origin).netloc != request.headers.get("host") and origin not in ALLOWED_ORIGINS):
        return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
    return await call_next(request)


from . import investigate, sync, workbench, workspaces  # noqa: E402  (routers; after app + middleware exist)

for module in (workspaces, sync, workbench, investigate):
    app.include_router(module.router)
