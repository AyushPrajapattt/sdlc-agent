"""FastAPI app: status, workspace, sync, SSE ask, static UI. Errors to clients are safe messages only."""

from __future__ import annotations

import json
import os
import threading
from urllib.parse import urlsplit
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from hackfront import config

config.load_env()
app = FastAPI(title="hackfront", docs_url=None, redoc_url=None)


@app.middleware("http")
async def same_origin_only(request, call_next):
    """CSRF guard: a browser page on another origin must not drive state-changing routes."""
    origin = request.headers.get("origin")
    if request.method not in ("GET", "HEAD") and origin and urlsplit(origin).netloc != request.headers.get("host"):
        return JSONResponse({"detail": "cross-origin request refused"}, status_code=403)
    return await call_next(request)
MODES = ("why", "debug", "change")
_sync_lock = threading.Lock()  # ponytail: single process, one sync at a time


class SyncBody(BaseModel):
    demo: bool = False


class AskBody(BaseModel):
    question: str
    mode: str = "why"
    provider: str | None = None


def _token_present() -> dict:
    env = os.environ.get
    return {
        "github": bool(env("GITHUB_TOKEN")),
        "jira": bool(env("JIRA_API_TOKEN") and env("JIRA_EMAIL")),
        "slack": bool(env("SLACK_BOT_TOKEN")),
    }


def _configured(ws: dict) -> dict:
    return {
        "github": bool(ws["github"]["repos"]),
        "jira": bool(ws["jira"]["projects"]),
        "slack": bool(ws["slack"]["channels"]),
    }


@app.get("/api/status")
def status() -> dict:
    try:
        from hackfront.ingest.sync import graph_counts

        neo4j = {"ok": True, "counts": graph_counts()}
    except Exception:  # noqa: BLE001 - never leak driver messages (may include URIs)
        neo4j = {"ok": False, "error": "Neo4j unreachable or not configured"}
    try:
        from hackfront.agent import providers

        provs = providers()
    except Exception:  # noqa: BLE001
        provs = []
    try:
        configured = _configured(config.load_workspace())
    except Exception:  # noqa: BLE001
        configured = dict.fromkeys(("github", "jira", "slack"), False)
    tokens = _token_present()
    sources = {k: {"configured": configured[k], "token_present": tokens[k]} for k in tokens}
    return {"neo4j": neo4j, "sources": sources, "providers": provs}


@app.get("/api/workspace")
def get_workspace() -> dict:
    try:
        return config.load_workspace()
    except Exception:  # noqa: BLE001
        raise HTTPException(500, "workspace.json is invalid") from None


@app.put("/api/workspace")
def put_workspace(data: dict) -> dict:
    try:
        return config.save_workspace(data)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


def _sync_response(summaries: list[dict]) -> dict:
    """`complete` is false if any stream failed or hit the page bound: the graph may be partial."""
    return {"summaries": summaries, "complete": all(s["complete"] for s in summaries)}


def _run_sync(workspace: dict, demo: bool):
    if not _sync_lock.acquire(blocking=False):
        raise HTTPException(409, "A sync is already running")
    try:
        from hackfront.ingest.sync import sync_workspace

        return sync_workspace(workspace, demo=demo)
    except RuntimeError as error:
        raise HTTPException(500, str(error)) from None
    except Exception:  # noqa: BLE001
        raise HTTPException(500, "Sync failed; see server logs") from None
    finally:
        _sync_lock.release()


@app.post("/api/sync")
def sync(body: SyncBody | None = None) -> dict:
    if body and body.demo:
        from hackfront.ingest.demo import DEMO_WORKSPACE

        return _sync_response(_run_sync(DEMO_WORKSPACE, True))
    return _sync_response(_run_sync(config.load_workspace(), False))


@app.post("/api/demo")
def demo() -> dict:
    from hackfront.ingest.demo import DEMO_WORKSPACE

    return _sync_response(_run_sync(DEMO_WORKSPACE, True))


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


@app.post("/api/ask")
def ask(body: AskBody):
    question = body.question.strip()
    if body.mode not in MODES:
        return JSONResponse({"detail": "mode must be why, debug or change"}, 422)
    if not question or len(question) > 8000:
        return JSONResponse({"detail": "question must be 1-8000 characters"}, 422)

    def stream():  # sync generator: Starlette iterates it in a worker thread
        try:
            from hackfront.agent import run

            for item in run(question, mode=body.mode, provider=body.provider or None):
                kind = item.get("event")
                if kind == "trace":
                    yield _sse("trace", {"node": item.get("node"), "data": item.get("data", {})})
                elif kind == "answer":
                    yield _sse("answer", {"answer": item.get("answer"), "evidence": item.get("evidence")})
                elif kind == "error":
                    yield _sse("error", {"message": str(item.get("message", "Agent error"))})
        except Exception:  # noqa: BLE001
            yield _sse("error", {"message": "The agent failed; see server logs"})

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


_web = Path(__file__).resolve().parents[3] / "web"
if _web.is_dir():
    app.mount("/", StaticFiles(directory=_web, html=True), name="web")
