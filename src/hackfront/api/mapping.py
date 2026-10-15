"""Graph rows -> the UI's Node / Edge shapes (see docs/workbench-api.md). Single source of truth for both."""

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
       a.change_paths AS paths, a.context_json AS context"""

EDGE_QUERY = """
MATCH (a:Artifact)-[r]->(b:Artifact) WHERE a.canonical_id IN $ids AND b.canonical_id IN $ids
RETURN a.canonical_id AS source, b.canonical_id AS target, type(r) AS rel,
       coalesce(r.origin, 'structural') AS origin, r.locator AS locator"""

ALL_IDS_QUERY = "MATCH (a:Artifact) WHERE NOT coalesce(a.is_stub, false) RETURN a.canonical_id AS id LIMIT $limit"


def _context(raw) -> dict:
    try:
        return json.loads(raw) if isinstance(raw, str) else {}
    except ValueError:
        return {}


def to_node(row: dict) -> dict:
    """One graph row -> UI Node. `id` is the canonical id; `scope` is the repo / Jira project / Slack channel."""
    provider, rtype, sid = row["provider"], row["rtype"], row["source_id"]
    author = row.get("author") or "unknown"
    ctx = _context(row.get("context"))
    if provider == "github":
        scope = row["workspace"]
        ref = sid[:7] if rtype == "commit" else f"#{sid}" if rtype == "pull_request" else f"@{author}"
    elif provider == "jira":
        scope = row["workspace"]
        ref = sid if rtype == "issue" else "comment"
    else:
        scope = str(ctx.get("channel_id") or row["workspace"])
        ref = f"#{scope}" if rtype == "thread" else f"@{author}"
    text = row.get("text") or ""
    return {
        "id": row["id"], "cid": row["id"], "kind": KIND.get(row["kind"], "discussion"), "source": provider,
        "ref": ref, "title": row.get("title") or (text[:80] + ("…" if len(text) > 80 else "")) or ref,
        "text": text, "author": author, "time": row.get("time") or "", "url": row.get("url") or "",
        "paths": list(row.get("paths") or []) or None, "scope": scope,
    }


def fetch_nodes(driver, ids) -> list[dict]:
    records, _, _ = driver.execute_query(NODE_QUERY, ids=list(ids), database_=config.neo4j_database(), routing_="r")
    return [to_node(r.data()) for r in records]


def fetch_edges(driver, ids) -> list[dict]:
    records, _, _ = driver.execute_query(EDGE_QUERY, ids=list(ids), database_=config.neo4j_database(), routing_="r")
    return [{"from": r["source"], "to": r["target"], "rel": r["rel"], "origin": r["origin"], "locator": r["locator"]}
            for r in records]


def graph_for(driver, ids) -> dict:
    """{nodes, edges} for exactly these ids (stubs excluded)."""
    nodes = fetch_nodes(driver, ids)
    return {"nodes": nodes, "edges": fetch_edges(driver, [n["id"] for n in nodes])}


def whole_graph(driver, limit: int = 3000) -> dict:
    records, _, _ = driver.execute_query(
        ALL_IDS_QUERY, limit=limit, database_=config.neo4j_database(), routing_="r")
    return graph_for(driver, [r["id"] for r in records])
