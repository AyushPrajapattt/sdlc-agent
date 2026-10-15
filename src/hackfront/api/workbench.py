"""Workbench endpoints: workspace overview, whole graph, repo files, per-line blame (docs/workbench-api.md)."""

from __future__ import annotations

import json
import re
from itertools import groupby

from fastapi import APIRouter, HTTPException

from .. import config
from ..ingest.blame import blame
from . import mapping

router = APIRouter()

_NAME = re.compile(r"[A-Za-z0-9._-]+")
_COMMITS = """
MATCH (c:Artifact {record_kind: 'git_commit', provider: 'github', workspace: $ws})
WHERE NOT coalesce(c.is_stub, false)
RETURN c.canonical_id AS id, c.event_time AS time, c.change_paths AS paths, c.raw_payload_json AS raw"""
_SCOPES = {
    "repos": "MATCH (a:Artifact {provider: 'github'}) WHERE NOT coalesce(a.is_stub, false) RETURN DISTINCT a.workspace AS v",
    "jira": "MATCH (a:Artifact {provider: 'jira'}) WHERE NOT coalesce(a.is_stub, false) RETURN DISTINCT a.workspace AS v",
    "slack": "MATCH (a:Artifact {provider: 'slack'}) WHERE NOT coalesce(a.is_stub, false) "
             "RETURN a.context_json AS v LIMIT 20000",  # ponytail: scans messages; index channel_id if this gets slow
    "indexed": "MATCH (c:Artifact {record_kind: 'git_commit', provider: 'github'}) WHERE NOT coalesce(c.is_stub, false) "
               "RETURN DISTINCT c.workspace AS v",
}


def check_repo(owner: str, repo: str) -> str:
    if not (_NAME.fullmatch(owner) and _NAME.fullmatch(repo)) or ".." in owner + repo:
        raise ValueError("owner and repo must match [A-Za-z0-9._-]+")
    return f"{owner}/{repo}"


def check_path(path: str) -> str:
    if (not path or len(path) > 300 or "\0" in path or "\\" in path or path.startswith("/")
            or any(part in ("", ".", "..") for part in path.split("/"))):
        raise ValueError("path must be a relative POSIX path of at most 300 characters without '..'")
    return path


def _commits(driver, ws: str) -> list[dict]:
    records, _, _ = driver.execute_query(_COMMITS, ws=ws, database_=config.neo4j_database(), routing_="r")
    rows = [r.data() if hasattr(r, "data") else dict(r) for r in records]
    if not rows:
        raise LookupError("no ingested commits for this repository")
    return rows


def _payload(row: dict) -> dict:
    try:
        data = json.loads(row.get("raw") or "{}")
    except ValueError:
        return {}
    return data if isinstance(data, dict) else {}


def _ordered(rows: list[dict]) -> list[dict]:
    """Oldest -> newest by event_time; ties broken so a commit follows its parents, then by id (stable)."""
    rows = sorted(rows, key=lambda r: (r.get("time") or "", r["id"]))
    out: list[dict] = []
    for _, group in groupby(rows, key=lambda r: r.get("time")):
        pending = list(group)
        while pending:
            ids = {r["id"].rsplit(":", 1)[-1] for r in pending}
            ready = next((r for r in pending
                          if not ids & {p.get("sha") for p in _payload(r).get("parents", []) if isinstance(p, dict)}),
                         pending[0])
            pending.remove(ready)
            out.append(ready)
    return out


def blame_for(driver, owner: str, repo: str, path: str) -> dict:
    """{path, lines:[{text, blame: commit canonical id}], complete, note?} by replaying ingested patches.

    ValueError for invalid input, LookupError when the repo/file has no ingested history."""
    ws, path = check_repo(owner, repo), check_path(path)
    rows = _commits(driver, ws)
    patches = []
    for row in _ordered(rows):
        for f in _payload(row).get("files", []):
            if not isinstance(f, dict):
                continue
            if f.get("filename") == path:
                patches.append((row["id"], f.get("patch") if isinstance(f.get("patch"), str) else None))
            elif f.get("previous_filename") == path:  # renamed away: content after this point is unknown
                patches.append((row["id"], None))
    if not patches:
        raise LookupError("file not found in ingested commits")
    return {"path": path, **blame(patches)}


def _with_driver(fn):
    """Run fn(driver) with a verified read driver; 503 if Neo4j is unavailable, 4xx for ValueError/LookupError."""
    try:
        driver = config.neo4j_driver()
    except Exception:  # noqa: BLE001 - driver errors may include URIs
        raise HTTPException(503, "Neo4j unreachable or not configured") from None
    try:
        return fn(driver)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    except LookupError as error:
        raise HTTPException(404, str(error)) from None
    except HTTPException:
        raise
    except Exception:  # noqa: BLE001
        raise HTTPException(500, "Query failed; see server logs") from None
    finally:
        driver.close()


@router.get("/api/graph")
def graph() -> dict:
    return _with_driver(mapping.whole_graph)


@router.get("/api/repo/{owner}/{repo}/files")
def files(owner: str, repo: str) -> dict:
    def run(driver):
        rows = _commits(driver, check_repo(owner, repo))
        return {"files": sorted({p for r in rows for p in (r.get("paths") or [])})}

    return _with_driver(run)


@router.get("/api/repo/{owner}/{repo}/file")
def file(owner: str, repo: str, path: str = "") -> dict:
    return _with_driver(lambda driver: blame_for(driver, owner, repo, path))


def _graph_scopes() -> dict:
    """Every scope present in the graph; empty lists if Neo4j is down."""
    out = {"repos": [], "jira": [], "slack": [], "indexed": []}
    try:
        driver = config.neo4j_driver()
    except Exception:  # noqa: BLE001
        return out
    try:
        for key, query in _SCOPES.items():
            records, _, _ = driver.execute_query(query, database_=config.neo4j_database(), routing_="r")
            values = {r["v"] for r in records if r["v"]}
            if key == "slack":
                values = {str(c) for c in (mapping._context(v).get("channel_id") for v in values) if c}
            out[key] = sorted(values)
    except Exception:  # noqa: BLE001
        pass
    finally:
        driver.close()
    return out


@router.get("/api/workbench")
def workbench() -> dict:
    from .app import _token_present

    try:
        ws = config.load_workspace()
    except Exception:  # noqa: BLE001
        ws = json.loads(json.dumps(config.EMPTY_WORKSPACE))
    owner = ws["github"]["owner"]
    connected = {
        "repos": [r if "/" in r else f"{owner}/{r}" for r in ws["github"]["repos"]],
        "jira": list(ws["jira"]["projects"]),
        "slack": list(ws["slack"]["channels"]),
    }
    scopes = _graph_scopes()
    catalog = {k: sorted({*connected[k], *scopes[k]}) for k in connected}
    try:
        from hackfront.ingest.sync import graph_counts

        neo4j = {"ok": True, "counts": graph_counts()}
    except Exception:  # noqa: BLE001
        neo4j = {"ok": False}
    try:
        from hackfront.agent import providers

        provs = providers()
    except Exception:  # noqa: BLE001
        provs = []
    tokens = _token_present()
    return {
        "workspace": {"slug": "local", "name": owner or "Local"},
        "connected": connected,
        "catalog": catalog,
        "indexed_repos": scopes["indexed"],
        "neo4j": neo4j,
        "sources": {k: {"token_present": v} for k, v in tokens.items()},
        "providers": provs,
    }
