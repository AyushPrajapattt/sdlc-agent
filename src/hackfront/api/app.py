"""FastAPI app: routers only (docs/workbench-api.md). Errors to clients are safe messages only."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from fastapi import FastAPI
from fastapi.responses import JSONResponse

from hackfront import config

config.load_env()
# The Next.js UI (web/) proxies /api/* here from whatever local port it runs on, so any localhost origin is trusted;
# extra origins (e.g. a LAN address) go in HACKFRONT_ORIGINS, comma-separated.
ALLOWED_ORIGINS = set(filter(None, os.environ.get("HACKFRONT_ORIGINS", "").split(",")))
LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}
app = FastAPI(title="hackfront", docs_url=None, redoc_url=None)


def trusted_origin(origin: str, host: str | None) -> bool:
    parts = urlsplit(origin)
    return (origin in ALLOWED_ORIGINS or parts.netloc == host
            or (parts.scheme in ("http", "https") and parts.hostname in LOCAL_HOSTS))


@app.middleware("http")
async def same_origin_only(request, call_next):
    """CSRF guard: a web page on another site must not drive state-changing routes."""
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD") and origin and not trusted_origin(origin, request.headers.get("host")):
        return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
    return await call_next(request)


from . import investigate, sync, workbench, workspaces  # noqa: E402  (routers; after app + middleware exist)

for module in (workspaces, sync, workbench, investigate):
    app.include_router(module.router)
