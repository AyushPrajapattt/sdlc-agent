"""Per-workspace sync job endpoints (docs/workbench-api.md). Owned by MVP-SYNC."""

import os

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from hackfront import config

router = APIRouter()


class SyncBody(BaseModel):
    mode: str = "standard"


@router.post("/api/w/{ws}/sync", status_code=202)
def start(ws: str, body: SyncBody | None = None) -> dict:
    from hackfront.ingest import sync

    try:
        config.check_slug(ws)
        if not all(os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD")):
            config.load_workspace(ws)  # 404 first for an unknown workspace
            raise HTTPException(503, "Neo4j is not configured")
        return sync.start_sync(ws, body.mode if body else "standard")
    except LookupError:
        raise HTTPException(404, "workspace not found") from None
    except RuntimeError:
        raise HTTPException(409, "a sync is already running") from None
    except ValueError as error:  # bad mode / no sources / bad id: messages are ours and safe
        raise HTTPException(422, str(error)) from None


@router.get("/api/w/{ws}/sync")
def status(ws: str) -> dict:
    from hackfront.ingest import sync

    try:
        config.load_workspace(ws)
        return sync.sync_status(ws)
    except LookupError:
        raise HTTPException(404, "workspace not found") from None
    except ValueError:
        raise HTTPException(404, "workspace not found") from None
