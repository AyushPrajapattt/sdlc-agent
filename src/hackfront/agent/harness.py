"""Cypher harness: fixed, parameterized, read-only tools. The LLM never writes Cypher.

Guards (all in code): tool in registry, arg type/length, id charset + id already seen in evidence,
row limits, query timeout, read routing, a static no-write check, EXPLAIN of every template at startup.
"""

from __future__ import annotations

import re

from neo4j import Query

from ..config import neo4j_database

MAX_ARG = 200
LIMIT, CHAIN_LIMIT, TIMEOUT_S = 10, 25, 10
TEXT_LEN, FULL_LEN = 600, 1_000_000
ID_RE = re.compile(r"[A-Za-z0-9._~%:\-]{1,200}")  # canonical_id: percent-quoted parts joined by ':'
WRITE_RE = re.compile(r"\b(CREATE|MERGE|DELETE|SET|REMOVE|DROP|LOAD|FOREACH|CALL|DETACH)\b", re.I)


class HarnessError(ValueError):
    """A tool call the harness refused (bad tool, bad argument, unseen id)."""


GRAPH_MODEL = """The evidence graph holds artifacts of five kinds: git_commit, pull_request, issue (Jira),
discussion_thread and discussion_message (Slack). Edges are evidence, never guesses: an edge exists only if a source
stated it. origin=structural means the source system itself links them (PR CONTAINS commit, message REPLIES_TO thread,
a review/comment REFERENCES its PR). origin=text means an explicit identifier was found in the text (a ticket key such
as PAY-412, a PR URL, a Slack permalink). Nothing is inferred from keywords or timing. REFERENCES points from the
artifact that mentions to the one mentioned; traversal ignores direction. Pointing at a record that was never
ingested yields a stub, which is not evidence and never returned."""

DESCRIPTIONS = {
    "find_text": "find_text(query): artifacts whose title+text contain ALL the words of the query (case-insensitive). "
                 "Use specific words, ticket keys (PAY-412), '#123' for PR numbers. Start here without a foothold.",
    "file_history": "file_history(path): commits/PRs that changed a file; path is a fragment such as 'src/pay/gateway.py'. "
                    "Chronological. Use for any question about a file.",
    "neighbors": "neighbors(id): artifacts directly linked (1 hop) to a known id, with via={rel, origin, from}. "
                 "id must be a canonical id already seen in evidence.",
    "evidence_chain": "evidence_chain(id): everything reachable within 3 hops over REFERENCES/CONTAINS/REPLIES_TO/CHANGES "
                      "(commit -> PR -> issue -> discussion), each once with hops and via. Best tool once you have a promising id.",
    "get": "get(id): the full untruncated text of one already-seen artifact.",
    "cypher_query": "cypher_query(question): escape hatch. A guarded read-only query is generated from your plain-language "
                    "question and only used to FIND artifacts. Prefer the fixed tools; use this only for multi-hop, "
                    "aggregate or filter questions they cannot express (e.g. 'issues referenced by text-origin edges "
                    "from threads'). Returns the same rows as the other tools.",
}

_RET = """a.canonical_id AS id, a.record_kind AS kind, a.title AS title,
       left(coalesce(a.text, ''), $n) AS text, a.source_uri AS url,
       a.event_time AS time, coalesce(a.change_paths, []) AS paths"""
_REAL = "coalesce(a.is_stub, false) = false"
_VIA = "{rel: type(r), origin: coalesce(r.origin, 'structural'), from: startNode(r).canonical_id}"

CYPHER = {
    "find_text": f"""MATCH (a:Artifact)
WHERE {_REAL} AND all(w IN $words WHERE toLower(coalesce(a.title, '') + ' ' + coalesce(a.text, '')) CONTAINS w)
RETURN {_RET} ORDER BY a.event_time DESC LIMIT $limit""",
    # newest $limit matches, returned chronologically
    "file_history": f"""MATCH (a:Artifact)
WHERE {_REAL} AND any(p IN coalesce(a.change_paths, []) WHERE p CONTAINS $path)
WITH a ORDER BY a.event_time DESC LIMIT $limit
RETURN {_RET} ORDER BY a.event_time ASC""",
    "neighbors": f"""MATCH (:Artifact {{canonical_id: $id}})-[r]-(a:Artifact)
WHERE {_REAL}
RETURN {_RET}, {_VIA} AS via LIMIT $limit""",
    "evidence_chain": f"""MATCH p = (s:Artifact {{canonical_id: $id}})-[:REFERENCES|CONTAINS|REPLIES_TO|CHANGES*1..3]-(a:Artifact)
WHERE a <> s AND {_REAL}
  AND all(e IN relationships(p) WHERE NOT (coalesce(e.locator, '') STARTS WITH '$.parents' OR e.locator = '$.base.sha'))
WITH a, p ORDER BY length(p)
WITH a, head(collect(p)) AS best
WITH a, length(best) AS hops, last(relationships(best)) AS r
RETURN {_RET}, hops, {_VIA} AS via ORDER BY hops, a.event_time LIMIT $limit""",
    "get": f"""MATCH (a:Artifact {{canonical_id: $id}}) WHERE {_REAL}
RETURN {_RET} LIMIT 1""",
    "hydrate": f"""MATCH (a:Artifact) WHERE a.canonical_id IN $ids AND {_REAL}
RETURN {_RET} LIMIT $limit""",
    "edges_among":"""MATCH (a:Artifact)-[r]->(b:Artifact)
WHERE a.canonical_id IN $ids AND b.canonical_id IN $ids
RETURN a.canonical_id AS source, b.canonical_id AS target, type(r) AS rel,
       coalesce(r.origin, 'structural') AS origin, r.locator AS locator LIMIT 300""",
}
_SAMPLE = {"words": ["x"], "path": "x", "id": "x", "ids": ["x"], "limit": 1, "n": 1}
_checked: set[int] = set()


def execute(driver, cypher: str, database: str | None = None, **params) -> list[dict]:
    """The only DB entry point: read routing, timeout, parameters only, static write refusal."""
    if WRITE_RE.search(cypher):
        raise HarnessError("write clauses are not allowed")
    records, _, _ = driver.execute_query(
        Query(cypher, timeout=TIMEOUT_S), params, database_=database or neo4j_database(), routing_="r")
    return [r.data() for r in records]


def selfcheck(driver, database: str | None = None) -> None:
    """EXPLAIN every template; raises on the first failure. Cached per driver."""
    if id(driver) in _checked:
        return
    for name, cypher in CYPHER.items():
        try:
            execute(driver, "EXPLAIN " + cypher, database, **{k: v for k, v in _SAMPLE.items() if "$" + k in cypher})
        except Exception as error:  # noqa: BLE001
            raise RuntimeError(f"harness template {name} failed EXPLAIN: {error}") from error
    _checked.add(id(driver))


STOP = {"the", "a", "an", "of", "to", "in", "on", "for", "is", "are", "was", "why", "how", "what", "do", "does", "did",
        "we", "our", "this", "that", "it", "and", "or", "at", "by", "with", "be", "can", "i"}


def stem(word: str) -> str:
    """Crude plural/tense stem so 'capped' finds 'cap' and 'retries' finds 'retrying'-style text (substring match)."""
    for suffix in ("ing", "ed", "es", "s"):
        if len(word) > len(suffix) + 3 and word.endswith(suffix):
            word = word[: -len(suffix)]
            break
    return word[:-1] if len(word) > 3 and word[-1] == word[-2] else word


def words(query: str) -> list[str]:
    tokens = [w.strip(".,;:?!") for w in re.findall(r"[\w\-./#]+", query.lower())]
    kept = [stem(w) for w in tokens if w and w not in STOP]
    return (kept or [w for w in tokens if w])[:8]


class Harness:
    def __init__(self, driver, database: str | None = None, cypher_llm=None):
        """cypher_llm(question, error_or_None) -> cypher string; enables cypher_query."""
        self.driver, self.database, self.cypher_llm = driver, database, cypher_llm
        self.cypher_log: list[dict] = []  # compact trace items for cypher_query; drained by the flow
        self.seen: set[str] = set()  # ids the planner may use: retrieved evidence + seeds from the question

    def see(self, ids) -> None:
        self.seen.update(i for i in ids if isinstance(i, str) and ID_RE.fullmatch(i))

    def _arg(self, tool: str, arg) -> str:
        if tool not in DESCRIPTIONS:
            raise HarnessError(f"unknown tool {tool!r}; tools: {sorted(DESCRIPTIONS)}")
        if not isinstance(arg, str):
            raise HarnessError("argument must be a string")
        arg = arg.strip()
        if not arg or len(arg) > MAX_ARG or any(ord(c) < 32 for c in arg):
            raise HarnessError(f"argument must be 1-{MAX_ARG} printable characters")
        if tool in ("neighbors", "evidence_chain", "get"):
            if not ID_RE.fullmatch(arg):
                raise HarnessError("id has invalid characters")
            if arg not in self.seen:
                raise HarnessError("id was not seen in retrieved evidence; find it with find_text/file_history first")
        return arg

    def _cypher_query(self, question: str) -> list[dict]:
        """Generated Cypher only finds ids; rows come from the fixed `hydrate` template (non-stub only)."""
        from .text2cypher import MAX_ROWS, candidate_ids, validate

        if not self.cypher_llm:
            raise HarnessError("cypher_query is not available")
        log, error, ids = {"question": question, "cypher": None, "error": None}, None, []
        self.cypher_log.append(log)
        for _ in range(3):  # first try + 2 repairs
            try:
                log["cypher"] = cypher = validate(self.cypher_llm(question, error))
                execute(self.driver, "EXPLAIN " + cypher, self.database)
                ids = candidate_ids(execute(self.driver, cypher, self.database))
                log["error"] = None
                break
            except Exception as e:  # noqa: BLE001 - fed back to the LLM, then surfaced in the trace only
                log["error"] = error = str(e)[:300]
        if not ids:
            return []
        by_id = {r["id"]: r for r in execute(self.driver, CYPHER["hydrate"], self.database,
                                             ids=ids, limit=len(ids), n=TEXT_LEN)}
        return [by_id[i] for i in ids if i in by_id][:MAX_ROWS]

    def call(self, tool: str, arg: str) -> list[dict]:
        arg = self._arg(tool, arg)
        if tool == "cypher_query":
            rows = self._cypher_query(arg)
            self.see(r["id"] for r in rows)
            return rows
        if tool == "find_text":
            ws = words(arg)
            if not ws:
                raise HarnessError("query has no searchable words")
            params = {"words": ws, "limit": LIMIT, "n": TEXT_LEN}
        elif tool == "file_history":
            params = {"path": arg.replace("\\", "/"), "limit": LIMIT, "n": TEXT_LEN}
        else:
            params = {"id": arg, "n": FULL_LEN if tool == "get" else TEXT_LEN,
                      "limit": CHAIN_LIMIT if tool == "evidence_chain" else LIMIT}
        rows, seen_ids = [], set()
        for row in execute(self.driver, CYPHER[tool], self.database, **params):
            if row["id"] in seen_ids:  # neighbors may return a node once per edge
                continue
            seen_ids.add(row["id"])
            rows.append(row)
        self.see(seen_ids)
        return rows

    def edges_among(self, ids) -> list[dict]:
        ids = [i for i in ids if isinstance(i, str) and ID_RE.fullmatch(i)]
        return execute(self.driver, CYPHER["edges_among"], self.database, ids=ids) if ids else []
