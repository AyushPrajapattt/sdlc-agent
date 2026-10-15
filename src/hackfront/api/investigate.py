"""Investigation endpoints: SSE investigate, stored investigations. Errors to clients are safe messages only."""

from __future__ import annotations

import json
import logging
import queue
import re
import threading

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, StrictInt

from hackfront import config

log = logging.getLogger("hackfront.investigate")
router = APIRouter()
MODES = ("why", "debug", "change")
MAX_CONCURRENT = 3
_slots = threading.BoundedSemaphore(MAX_CONCURRENT)  # ponytail: per-process; use a shared limiter if run multi-worker
MODEL_RE = re.compile(r"[\w.:/\-]{1,100}")


class InvestigateBody(BaseModel):
    question: str
    mode: str = "why"
    provider: str | None = None
    model: str | None = None
    file: str | None = None
    line: StrictInt | None = None
    repo: str | None = None  # "owner/repo"; optional when the workspace connects exactly one repository


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data, default=str)}\n\n"


def _bad_path(path: str) -> bool:
    parts = path.split("/")
    return (not 0 < len(path) <= 300 or path.startswith("/") or "\\" in path or re.match(r"^[A-Za-z]:", path) is not None
            or any(c in ("", ".", "..") for c in parts) or any(ord(ch) < 32 for ch in path))


def _invalid(body: InvestigateBody) -> str | None:
    from hackfront.agent.llm import PROVIDERS

    if not 1 <= len(body.question.strip()) <= 8000:
        return "question must be 1-8000 characters"
    if body.mode not in MODES:
        return "mode must be why, debug or change"
    if body.provider is not None and body.provider not in PROVIDERS:
        return "unknown provider"
    if body.model is not None and not MODEL_RE.fullmatch(body.model):
        return "invalid model name"
    if (body.file is None) != (body.line is None):
        return "file and line must be given together"
    if body.file is not None and _bad_path(body.file):
        return "file must be a relative POSIX path without '..'"
    if body.line is not None and body.line < 1:
        return "line must be a positive integer"
    if body.repo is not None and not re.fullmatch(r"[A-Za-z0-9._-]+/[A-Za-z0-9._-]+", body.repo):
        return "repo must look like owner/repo"
    return None


def _scopes(ws: str) -> dict:
    """The workspace's connected targets; 404 for a bad or unknown workspace."""
    try:
        return config.scopes(ws)
    except (ValueError, LookupError):
        raise HTTPException(404, "Workspace not found") from None


def _anchor(driver, repos: list[str], repo: str | None, file: str, line: int) -> dict:
    """{file, line, text, blame_id}: the line's text and the commit blamed for it, from the ingested patches."""
    from . import workbench

    try:
        if repo is None:  # the UI knows the repo; a single connected repo is unambiguous without it
            if len(repos) != 1:
                raise HTTPException(422, "repo (owner/repo) is required unless the workspace connects exactly one repository")
            repo = repos[0]
        elif repo not in repos:
            raise LookupError("repository is not connected to this workspace")
        owner, _, name = repo.partition("/")
        got = workbench.blame_for(driver, owner, name, file)
    except HTTPException:
        raise
    except (LookupError, ValueError):
        raise HTTPException(404, "That file is not in the ingested history") from None
    except Exception:  # noqa: BLE001
        log.exception("blame_for failed")
        raise HTTPException(422, "Could not resolve that file and line") from None
    if not got.get("complete"):
        raise HTTPException(422, f"Blame is incomplete for this file: {got.get('note') or 'history missing'}")
    lines = got.get("lines") or []
    if not 1 <= line <= len(lines):
        raise HTTPException(404, "That line is not in the file")
    return {"file": file, "line": line, "text": lines[line - 1]["text"], "blame_id": lines[line - 1]["blame"]}


@router.post("/api/w/{ws}/investigate")
def investigate(ws: str, body: InvestigateBody):
    targets = _scopes(ws)
    error = _invalid(body)
    if error:
        return JSONResponse({"detail": error}, 422)
    scopes = [*targets["repos"], *targets["jira"], *targets["slack"]]
    if not _slots.acquire(blocking=False):
        return JSONResponse({"detail": f"At most {MAX_CONCURRENT} investigations can run at once; try again shortly"}, 429)
    driver = None
    try:
        try:
            config.load_env()
            driver = config.neo4j_driver()
        except Exception:  # noqa: BLE001 - driver messages may contain URIs
            raise HTTPException(503, "Neo4j unreachable or not configured") from None
        anchor = _anchor(driver, targets["repos"], body.repo, body.file, body.line) if body.file else None
        out: queue.Queue = queue.Queue()

        def work():
            try:
                from hackfront.agent.investigation import investigate as run, save

                for ev in run(body.question.strip(), body.mode, body.provider, body.model, driver, anchor,
                              scopes=scopes, workspace=ws):
                    if ev["event"] == "trace":
                        out.put(_sse("trace", {"step": ev["step"]}))
                    elif ev["event"] == "investigation":
                        try:
                            save(ev["investigation"], ev["graph"], ws)
                        except Exception:  # noqa: BLE001 - the answer is still worth delivering
                            log.exception("could not persist investigation")
                        out.put(_sse("investigation", {"investigation": ev["investigation"], "graph": ev["graph"]}))
                    else:
                        out.put(_sse("error", {"message": str(ev.get("message", "Agent error"))[:300]}))
            except Exception:  # noqa: BLE001
                log.exception("investigation failed")
                out.put(_sse("error", {"message": "The investigation failed; see server logs"}))
            finally:
                driver.close()
                _slots.release()
                out.put(None)

        threading.Thread(target=work, daemon=True).start()  # runs to completion even if the client disconnects
    except BaseException:
        if driver is not None:
            driver.close()
        _slots.release()
        raise

    def stream():
        while (item := out.get()) is not None:
            yield item

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache"})


@router.get("/api/w/{ws}/investigations")
def list_investigations(ws: str) -> list[dict]:
    from hackfront.agent.investigation import list_all

    _scopes(ws)
    return list_all(ws)


@router.get("/api/w/{ws}/investigations/{iid}")
def get_investigation(ws: str, iid: str) -> dict:
    from hackfront.agent.investigation import get

    _scopes(ws)
    found = get(iid, ws)
    if found is None:
        raise HTTPException(404, "Investigation not found")
    return found
