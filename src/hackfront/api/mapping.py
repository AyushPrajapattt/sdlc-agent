"""Graph rows -> the UI's Node / Edge shapes (see docs/workbench-api.md). Single source of truth for both.

Workspace isolation: every artifact stores a `scope` (repo `owner/repo`, Jira project key, Slack channel id) and a
workspace only sees artifacts whose scope is one of its connected targets (`flat_scopes`).
"""

from __future__ import annotations

import json

from .. import config

KIND = {"git_commit": "commit", "pull_request": "pr", "issue": "issue",
        "discussion_thread": "discussion", "discussion_message": "discussion"}

NODE_QUERY = """
MATCH (a:Artifact) WHERE a.canonical_id IN $ids AND NOT coalesce(a.is_stub, false)
RETURN a.canonical_id AS id, a.provider AS provider, a.workspace AS workspace, a.source_record_type AS rtype,
       a.source_id AS source_id, a.record_kind AS kind, a.title AS title, a.text AS text, a.source_uri AS url,
       a.event_time AS time, coalesce(a.actor_handle, a.actor_display_name, a.actor_source_id) AS author,
       a.change_paths AS paths, a.context_json AS context, a.scope AS scope"""

EDGE_QUERY = """
MATCH (a:Artifact)-[r]->(b:Artifact) WHERE a.canonical_id IN $ids AND b.canonical_id IN $ids
RETURN a.canonical_id AS source, b.canonical_id AS target, type(r) AS rel,
       coalesce(r.origin, 'structural') AS origin, r.locator AS locator"""

SCOPED_IDS_QUERY = """
MATCH (a:Artifact) WHERE NOT coalesce(a.is_stub, false) AND a.scope IN $scopes
RETURN a.canonical_id AS id LIMIT $limit"""


def flat_scopes(scopes: dict) -> list[str]:
    """{'repos': [...], 'jira': [...], 'slack': [...]} (config.scopes) -> the flat list stored in Artifact.scope."""
    return [*scopes["repos"], *scopes["jira"], *scopes["slack"]]


def _context(raw) -> dict:
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        return {}


def to_node(row: dict, names: dict | None = None) -> dict:
    """One graph row -> UI Node. `id` is the canonical id; `scope` is the repo / Jira project / Slack channel."""
    names = names or {}
    provider, rtype, sid = row["provider"], row["rtype"], row["source_id"]
    author = row.get("author") or "unknown"
    ctx = _context(row.get("context"))
    if provider == "slack":
        author = names.get("users", {}).get(author, author)
    if provider == "github":
        scope = row.get("scope") or row["workspace"]
        ref = sid[:7] if rtype == "commit" else f"#{sid}" if rtype == "pull_request" else f"@{author}"
    elif provider == "jira":
        scope = row.get("scope") or row["workspace"]
        ref = sid if rtype == "issue" else "comment"
    else:
        scope = str(ctx.get("channel_id") or row["workspace"])
        channel = names.get("channels", {}).get(scope, scope).lstrip("#")
        ref = f"#{channel}" if rtype == "thread" else f"@{author}"
    text = row.get("text") or ""
    return {
        "id": row["id"], "cid": row["id"], "kind": KIND.get(row["kind"], "discussion"), "source": provider,
        "ref": ref, "title": row.get("title") or (text[:80] + ("…" if len(text) > 80 else "")) or ref,
        "text": text, "author": author, "time": row.get("time") or "", "url": row.get("url") or "",
        "paths": list(row.get("paths") or []) or None, "scope": scope,
    }


def fetch_nodes(driver, ids, names: dict | None = None) -> list[dict]:
    records, _, _ = driver.execute_query(NODE_QUERY, ids=list(ids), database_=config.neo4j_database(), routing_="r")
    return [to_node(r.data(), names) for r in records]


def fetch_edges(driver, ids) -> list[dict]:
    records, _, _ = driver.execute_query(EDGE_QUERY, ids=list(ids), database_=config.neo4j_database(), routing_="r")
    return [{"from": r["source"], "to": r["target"], "rel": r["rel"], "origin": r["origin"], "locator": r["locator"]}
            for r in records]


def graph_for(driver, ids, names: dict | None = None) -> dict:
    """{nodes, edges} for exactly these ids (stubs excluded)."""
    nodes = fetch_nodes(driver, ids, names)
    return {"nodes": nodes, "edges": fetch_edges(driver, [n["id"] for n in nodes])}


def whole_graph(driver, scopes: list[str], names: dict | None = None, limit: int = 3000) -> dict:
    """Every non-stub artifact whose scope is in `scopes` (cap `limit`)."""
    records, _, _ = driver.execute_query(
        SCOPED_IDS_QUERY, scopes=list(scopes), limit=limit, database_=config.neo4j_database(), routing_="r")
    return graph_for(driver, [r["id"] for r in records], names)
