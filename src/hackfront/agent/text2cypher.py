"""Guarded text2cypher: an LLM-written READ query is used only to FIND ids; rows are then hydrated by a fixed template."""

from __future__ import annotations

import re

from .harness import ID_RE, HarnessError

MAX_ROWS = 25
FORBIDDEN = re.compile(r"\b(CREATE|MERGE|DELETE|DETACH|SET|REMOVE|DROP|LOAD|FOREACH|CALL|UNION|APOC|DBMS|PERIODIC"
                       r"|SHOW|TERMINATE|USE|INSERT|START|STOP|GRANT|DENY|REVOKE|ALTER|RENAME|REDUCE|RANGE|REPEAT)\b", re.I)
STARTS = re.compile(r"(MATCH|OPTIONAL\s+MATCH|WITH|UNWIND|RETURN)\b", re.I)  # admin/schema commands start otherwise
_LITERALS = re.compile(r"'(?:[^'\\]|\\.)*'|\"(?:[^\"\\]|\\.)*\"|`[^`]*`")
_LIMIT = re.compile(r"\bLIMIT\s+(\d+)\s*$", re.I)

SCHEMA_CARD = """Neo4j graph. One node label: (:Artifact) with properties canonical_id (unique id), record_kind
(git_commit | pull_request | issue | discussion_thread | discussion_message), title, text, source_uri, scope (repo owner/repo, Jira project key or Slack channel id), event_time
(ISO-8601 string, sortable), change_paths (list of file paths), provider (github|jira|slack), actor_display_name,
actor_handle, is_stub (true = referenced but never ingested; filter with coalesce(a.is_stub,false) = false).
Relationship types between Artifacts: REFERENCES, CONTAINS (pull_request -> commit), REPLIES_TO, PARENT_OF, CHANGES.
Relationship properties: origin ('structural' | 'text'), locator (string; '$.parents...' marks commit-parent edges), kind.
Scope is enforced for you: results outside the workspace are dropped, so do not filter on it.
Return the Artifact nodes (or their canonical_id) you want found. Read-only, single statement, no parameters, no procedures.
Examples:
MATCH (i:Artifact {record_kind:'issue'})<-[:REFERENCES]-(p:Artifact {record_kind:'pull_request'}) WHERE toLower(i.title) CONTAINS 'retry' RETURN p
MATCH (c:Artifact {record_kind:'git_commit'}) WHERE any(x IN c.change_paths WHERE x CONTAINS 'gateway') RETURN c ORDER BY c.event_time DESC LIMIT 10
MATCH (t:Artifact {record_kind:'discussion_thread'})-[r:REFERENCES]-(i:Artifact {record_kind:'issue'}) WHERE r.origin = 'text' RETURN t, i"""


def validate(cypher: str) -> str:
    """Return the query with a row cap enforced, or raise HarnessError."""
    if not isinstance(cypher, str) or not cypher.strip():
        raise HarnessError("empty query")
    q = cypher.strip().rstrip(";").strip()
    skeleton = _LITERALS.sub("''", q)  # keywords inside string literals are harmless
    if not STARTS.match(skeleton):
        raise HarnessError("query must start with MATCH, OPTIONAL MATCH, WITH, UNWIND or RETURN")
    if "//" in skeleton or "/*" in skeleton:
        raise HarnessError("comments are not allowed")
    if ";" in skeleton:
        raise HarnessError("only a single statement is allowed")
    if "$" in skeleton:
        raise HarnessError("parameters are not allowed; use literal values")
    if m := FORBIDDEN.search(skeleton):
        raise HarnessError(f"{m.group(1).upper()} is not allowed in a read-only query")
    if not re.search(r"\bRETURN\b", skeleton, re.I):
        raise HarnessError("query must contain RETURN")
    last = _LIMIT.search(skeleton)
    if not last:
        return f"{q} LIMIT {MAX_ROWS}"
    if int(last.group(1)) > MAX_ROWS:
        return _LIMIT.sub(f"LIMIT {MAX_ROWS}", q)
    return q


def candidate_ids(rows: list[dict]) -> list[str]:
    """Every canonical_id-shaped value in the result (node maps, strings, nested lists), in order, deduped."""
    found: dict[str, None] = {}

    def walk(v):
        if isinstance(v, dict):
            if isinstance(v.get("canonical_id"), str):
                found[v["canonical_id"]] = None
            for x in v.values():
                walk(x)
        elif isinstance(v, (list, tuple)):
            for x in v:
                walk(x)
        elif isinstance(v, str) and ":" in v and ID_RE.fullmatch(v):
            found[v] = None

    walk(rows)
    return list(found)[:100]
