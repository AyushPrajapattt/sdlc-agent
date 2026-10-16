"""Assemble the UI's Investigation JSON (docs/workbench-api.md) from the agent flow, and persist it.

Everything here except the claims text is deterministic: excluded reasons, checks, afterStep, confidence.
"""

from __future__ import annotations

import json
import os
import re
import secrets
from datetime import datetime, timezone
from typing import Iterator

from . import flow, prompts as P
from .harness import execute

ID_OK = re.compile(r"[a-z0-9-]{1,80}")
KEYWORD_ONLY = "Keyword match only: no explicit link to the evidence used."
LINKED = "Linked, but not needed for this answer."
COMMITS_Q = """MATCH (a:Artifact) WHERE a.record_kind = 'git_commit' AND coalesce(a.is_stub, false) = false
  AND $file IN coalesce(a.change_paths, []) AND ($scopes IS NULL OR a.scope IN $scopes)
RETURN a.canonical_id AS id, a.title AS title, a.event_time AS time, a.source_id AS sid ORDER BY a.event_time"""
ISSUES_Q = """MATCH (a:Artifact) WHERE a.canonical_id IN $ids AND a.provider = 'jira' AND a.record_kind = 'issue'
  AND ($scopes IS NULL OR a.scope IN $scopes)
RETURN a.canonical_id AS id, a.source_id AS key, a.context_json AS context"""


def new_id(question: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", question.lower()).strip("-")[:60].strip("-") or "q"
    return f"{slug}-{secrets.token_hex(3)}"


def _when(text):
    try:
        t = datetime.fromisoformat(str(text).replace("Z", "+00:00"))
    except ValueError:
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _checks(driver, file: str | None, cited: list[str], evidence: dict, scopes: list[str] | None) -> list[dict]:
    out = []
    if file:
        commits = [evidence[i] for i in cited if evidence[i].get("kind") == "git_commit"]
        newest = max((c for c in commits if _when(c.get("time"))), key=lambda c: _when(c["time"]), default=None)
        label = f"Later commits touching {file}"
        if not newest:
            out.append({"label": label, "state": "unknown", "detail": "No commit is cited, so there is no baseline to compare."})
        else:
            try:
                later = [r for r in execute(driver, COMMITS_Q, file=file, scopes=scopes)
                         if _when(r["time"]) and _when(r["time"]) > _when(newest["time"])]
                shown = "; ".join(f"{(r['sid'] or '')[:7]} {r['title'] or ''}".strip() for r in later[:5])
                out.append({"label": label, "state": "changed" if later else "holds",
                            "detail": f"{len(later)} commit(s) after {newest['time'][:10]}: {shown}" if later
                            else f"0 commits after {newest['time'][:10]}."})
            except Exception:  # noqa: BLE001
                out.append({"label": label, "state": "unknown", "detail": "Could not query later commits."})
    try:
        rows = execute(driver, ISSUES_Q, ids=cited, scopes=scopes) if cited else []
    except Exception:  # noqa: BLE001
        rows = []
    for r in rows:
        try:
            status = (json.loads(r["context"] or "{}") or {}).get("status")
        except (ValueError, AttributeError):
            status = None
        out.append({"label": f"{r['key']} status", "state": "unknown",
                    "detail": f"Jira status: {status} (as of last sync)" if status else "Jira status not ingested."})
    return out


def _steps(ev: dict, anchor: dict | None) -> list[tuple[dict, list[str]]]:
    """One trace event -> [(Step, evidence ids it surfaced)]."""
    node, u = ev["node"], ev["update"]
    if node == "understand":
        intent = u["understanding"].intent
        detail = f"Anchor {anchor['file']}:{anchor['line']} · intent: {intent}" if anchor else f"intent: {intent}"
        return [({"kind": "understand", "label": "Understand question", "detail": detail, "ms": ev["ms"]}, [])]
    if node in ("seed", "retrieve"):
        return [({"kind": "tool", "label": c["label"], "ms": c["ms"],
                  "detail": f"refused: {c['error']}" if c["error"] else f"{c['rows']} rows"}, c["ids"])
                for c in u.get("ran", [])]
    if node == "plan":
        return [({"kind": "plan", "label": "Plan", "detail": u["plan"].reasoning, "ms": ev["ms"]}, [])]
    if node == "evaluate":
        c = u["check"]
        return [({"kind": "gap", "label": "Find gaps", "ms": ev["ms"],
                  "detail": c.gap or "Evidence judged sufficient"}, [])]
    return []


def assemble(question: str, mode: str, anchor: dict | None, state: dict, h, steps: list[dict], first_seen: dict,
             provider: str, model: str, synth_ms: int, id: str | None = None) -> dict:
    evidence, final = state["evidence"], state["final"]
    cited = list(dict.fromkeys(ci["node"] for c in final["claims"] for ci in c["cites"]))
    ids = cited + [i for i in evidence if i not in cited]
    edges = h.edges_among(ids)
    linked = {e["source"] for e in edges if e["target"] in cited} | {e["target"] for e in edges if e["source"] in cited}
    counts = {s: sum(c["status"] == s for c in final["claims"]) for s in ("supported", "inferred", "unknown")}
    steps = steps + [{"kind": "synthesize", "label": "Synthesize", "ms": synth_ms,
                      "detail": f"{len(final['claims'])} claims · {counts['supported']} supported · "
                                f"{counts['inferred']} inferred · {counts['unknown']} unknown"}]
    last, gap_idx = len(steps) - 1, max((i for i, s in enumerate(steps) if s["kind"] == "gap"), default=None)
    claims = []
    for n, c in enumerate(final["claims"], 1):
        seen = [first_seen[ci["node"]] for ci in c["cites"] if ci["node"] in first_seen]
        after = max(seen) if seen else gap_idx if gap_idx is not None else last
        claims.append({"id": f"c{n}", "text": c["text"], "status": c["status"], "cites": c["cites"],
                       "afterStep": min(after, last), **({"note": c["note"]} if c["note"] else {})})
    inv = {"id": id or new_id(question), "question": question, "mode": mode,
           **({"file": anchor["file"], "line": anchor["line"]} if anchor else {}),
           "summary": final["summary"], "nodes": ids, "claims": claims, "gaps": final["gaps"], "trace": steps,
           "checks": _checks(h.driver, anchor["file"] if anchor else None, cited, evidence, h.scopes),
           "excluded": [{"node": i, "reason": LINKED if i in linked else KEYWORD_ONLY} for i in evidence if i not in cited],
           "confidence": final["confidence"], "provider": provider, "model": model, "prompt_version": P.PROMPT_VERSION,
           "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")}
    return inv


def investigate(question: str, mode: str = "why", provider: str | None = None, model: str | None = None,
                driver=None, anchor: dict | None = None, scopes: list[str] | None = None,
                workspace: str | None = None) -> Iterator[dict]:
    """Yield {event:trace, step} as steps complete, then {event:investigation, investigation, graph} (or {event:error})."""
    from .. import config
    from ..api.mapping import graph_for  # lazy: hackfront.api imports this package

    anchor = flow._anchor(anchor)
    steps: list[dict] = []
    first_seen: dict[str, int] = {}
    synth_ms = 0
    for ev in flow.stream(question, mode, provider, model, driver, anchor, scopes, workspace):
        if ev["event"] == "error":
            yield ev
            return
        if ev["event"] == "trace":
            if ev["node"] in ("synthesize", "verify"):
                synth_ms += ev["ms"]
                continue
            for step, ids in _steps(ev, anchor):
                steps.append(step)
                for i in ids:
                    first_seen.setdefault(i, len(steps) - 1)
                yield {"event": "trace", "step": step}
            continue
        try:
            inv = assemble(question, mode, anchor, ev["state"], ev["h"], steps, first_seen, ev["provider"], ev["model"],
                           synth_ms)
            graph = graph_for(ev["h"].driver, inv["nodes"], config.names(workspace) if workspace else None)
        except Exception as error:  # noqa: BLE001
            yield {"event": "error", "message": f"could not assemble the investigation ({type(error).__name__})"}
            return
        yield {"event": "trace", "step": inv["trace"][-1]}
        yield {"event": "investigation", "investigation": inv, "graph": graph}


# --- persistence (per workspace; backend chosen by HACKFRONT_STATE, see state.py) -------------

def save(investigation: dict, graph: dict, workspace: str) -> None:
    """Store {investigation, graph}; the graph snapshot keeps quotes verifiable if the graph changes."""
    from .. import state

    iid = investigation["id"]
    if not ID_OK.fullmatch(iid):
        raise ValueError("invalid investigation id")
    state.backend().put_investigation(workspace, iid, {"investigation": investigation, "graph": graph})


def get(iid: str, workspace: str) -> dict | None:
    from .. import state

    if not isinstance(iid, str) or not ID_OK.fullmatch(iid):
        return None
    return state.backend().get_investigation(workspace, iid)


def list_all(workspace: str, limit: int = 200) -> list[dict]:
    from .. import state

    return state.backend().list_investigations(workspace, limit)
