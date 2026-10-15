"""LangGraph investigation flow.

understand -> seed -> plan -> retrieve -> evaluate -(insufficient & attempts left)-> plan
                                                   \\-(sufficient | cap)-> synthesize -> verify
"""

from __future__ import annotations

import operator
import os
import re
import time
from typing import Annotated, Iterator, TypedDict

from langgraph.graph import END, StateGraph

from . import llm, prompts as P
from .harness import ID_RE, Harness, HarnessError
from .text2cypher import SCHEMA_CARD
from .verify import NOT_ESTABLISHED, to_legacy, verify

MAX_ATTEMPTS = int(os.environ.get("AGENT_MAX_ATTEMPTS", "3"))
MAX_QUESTION = 20_000
EXTS = "py|js|jsx|ts|tsx|java|kt|go|rb|rs|cs|cpp|c|h|php|sql|json|ya?ml|toml|md|sh|xml|gradle"
PATH_RE = re.compile(rf"(?<![\w.\-])((?:[/\\]?[\w.\-]+[/\\])*[\w.\-]+\.(?:{EXTS}))\b")
KEY_RE = re.compile(r"\b[A-Z][A-Z0-9]{1,9}-\d+\b")
PR_RE = re.compile(r"(?:\bPR|\bpull request|\bpull)\s*#?(\d+)|(?<![\w&])#(\d+)\b", re.I)
ID_IN_TEXT = re.compile(r"\b(?:github|jira|slack):[\w.%~-]+:[\w.%~-]+:[\w.%~-]+\b")
NOT_KEYS = ("UTF", "SHA", "ISO", "TLS", "SSL", "AES", "RFC", "MD", "HTTP", "CVE")
VENDORED = ("site-packages", "node_modules", "/usr/lib", "dist-packages")


# --- deterministic seeds (pure) -------------------------------------------------------

def extract_seeds(text: str, max_each: int = 4) -> list[tuple[str, str]]:
    """File paths -> file_history, ticket keys and PR numbers -> find_text. Order of first appearance."""
    paths, keys, prs = [], [], []
    for m in PATH_RE.finditer(text):
        path = m.group(1).replace("\\", "/")
        if any(v in path for v in VENDORED):
            continue
        parts = path.strip("/").split("/")
        path = "/".join(parts[-3:])  # repo-relative guess: tracebacks carry absolute prefixes
        if path not in paths:
            paths.append(path)
    for key in KEY_RE.findall(text):
        if not key.startswith(NOT_KEYS) and key not in keys:
            keys.append(key)
    for m in PR_RE.finditer(text):
        pr = f"#{m.group(1) or m.group(2)}"
        if pr not in prs:
            prs.append(pr)
    return ([("file_history", p) for p in paths[:max_each]] + [("find_text", k) for k in keys[:max_each]]
            + [("find_text", p) for p in prs[:max_each]])


def extract_ids(text: str) -> list[str]:
    return [i for i in ID_IN_TEXT.findall(text) if ID_RE.fullmatch(i)]


# --- state ----------------------------------------------------------------------------

class State(TypedDict, total=False):
    question: str
    mode: str
    understanding: P.Understanding
    plan: P.Plan
    done_calls: Annotated[list[str], operator.add]
    rejected: Annotated[list[str], operator.add]
    cypher: list
    evidence: dict[str, dict]
    attempts: int
    check: P.Sufficiency
    answer: dict | None
    final: dict
    anchor: dict | None
    ran: Annotated[list[dict], operator.add]  # one record per executed tool call: label, rows, ids, ms, error


def render(evidence: dict[str, dict], text_len: int) -> str:
    if not evidence:
        return "(none)"
    out = []
    for e in evidence.values():
        via = e.get("via")
        out.append(f"- [{e['id']}] {e['kind']} {e.get('time') or ''} url: {e.get('url') or '(none)'}\n"
                   f"  title: {e.get('title') or ''}\n  paths: {e.get('paths') or ''}\n"
                   + (f"  linked via {via['rel']} ({via['origin']}) from {via['from']}\n" if via else "")
                   + f"  text: {(e.get('text') or '')[:text_len]}")
    return "\n".join(out)


def route(s: State) -> str:
    return "synthesize" if s["check"].sufficient or s["attempts"] >= MAX_ATTEMPTS else "plan"


def build(h: Harness, provider: str, model: str):
    ask = lambda template, schema, **f: llm.structured(provider, template, schema, model, **f)  # noqa: E731

    def run_calls(calls, s):
        evidence, done, rejected, ran = dict(s.get("evidence") or {}), [], [], []
        for tool, arg in calls:
            key = f"{tool}({arg})"
            if key in (s.get("done_calls") or []) or key in done:
                continue
            done.append(key)
            t0, label = time.perf_counter(), f'{tool}("{arg[:60]}")'
            try:
                rows = h.call(tool, arg)
            except Exception as error:  # noqa: BLE001  harness refusal or transient DB error: report, keep going
                rejected.append(f"{key}: {type(error).__name__}: {str(error)[:120]}")
                ran.append({"label": label, "rows": 0, "ids": [], "ms": int((time.perf_counter() - t0) * 1000),
                            "error": f"{type(error).__name__}: {str(error)[:120]}"})
                continue
            ran.append({"label": label, "rows": len(rows), "ids": [r["id"] for r in rows],
                        "ms": int((time.perf_counter() - t0) * 1000), "error": None})
            for row in rows:
                evidence.setdefault(row["id"], row)
        cypher, h.cypher_log[:] = [{**c, "cypher": (c["cypher"] or "")[:500]} for c in h.cypher_log], []
        return {"evidence": evidence, "done_calls": done, "rejected": rejected, "cypher": cypher, "ran": ran}

    def understand(s):
        return {"understanding": ask(P.UNDERSTAND, P.Understanding, graph_model=P.GRAPH_MODEL,
                                     task=P.MODE_TASK[s["mode"]], question=s["question"]),
                "attempts": 0, "evidence": {}}

    def seed(s):
        h.see(extract_ids(s["question"]))
        calls, a = [], s.get("anchor")
        if a:  # the question is about one line: its file history and the commit that last changed it
            calls.append(("file_history", a["file"]))
            if a.get("blame_id"):
                h.see([a["blame_id"]])
                calls.append(("evidence_chain", a["blame_id"]))
        calls += extract_seeds(s["question"]) if s["mode"] == "debug" else []
        return run_calls(calls, s)

    def plan(s):
        u, check = s["understanding"], s.get("check")
        return {"plan": ask(P.PLAN, P.Plan, graph_model=P.GRAPH_MODEL, tools=P.TOOLS_TEXT, task=P.MODE_TASK[s["mode"]],
                            intent=u.intent, entities=u.entities, attempt=s["attempts"] + 1, max_attempts=MAX_ATTEMPTS,
                            done_calls=s.get("done_calls") or "(none)", rejected=s.get("rejected") or "(none)",
                            evidence=render(s["evidence"], 150), gap=check.gap if check else "(first attempt)")}

    def retrieve(s):
        out = run_calls([(c.tool, c.arg) for c in s["plan"].calls[:5]], s)
        return {**out, "attempts": s["attempts"] + 1}

    def evaluate(s):
        if not s["evidence"]:  # nothing to judge; skip the LLM call
            return {"check": P.Sufficiency(sufficient=False, relevant_ids=[], gap="no evidence retrieved yet")}
        return {"check": ask(P.SUFFICIENCY, P.Sufficiency, task=P.MODE_TASK[s["mode"]], question=s["question"],
                             evidence=render(s["evidence"], 600))}

    def synthesize(s):
        if not s["evidence"]:  # AC-7: no evidence, no LLM, no guess
            return {"answer": None}
        check = s["check"]
        relevant = {i: s["evidence"][i] for i in check.relevant_ids if i in s["evidence"]} or s["evidence"]
        return {"answer": ask(P.SYNTHESIZE, P.Synthesis, task=P.MODE_TASK[s["mode"]], question=s["question"],
                              sufficient=check.sufficient, evidence=render(relevant, 600)).model_dump()}

    def verify_node(s):
        if not s["evidence"]:
            return {"final": dict(NOT_ESTABLISHED)}
        return {"final": verify(s["answer"], s["evidence"], s["check"].sufficient, s["check"].gap)}

    g = StateGraph(State)
    for name, fn in [("understand", understand), ("seed", seed), ("plan", plan), ("retrieve", retrieve),
                     ("evaluate", evaluate), ("synthesize", synthesize), ("verify", verify_node)]:
        g.add_node(name, fn)
    g.set_entry_point("understand")
    for a, b in [("understand", "seed"), ("seed", "plan"), ("plan", "retrieve"), ("retrieve", "evaluate"),
                 ("synthesize", "verify"), ("verify", END)]:
        g.add_edge(a, b)
    g.add_conditional_edges("evaluate", route, {"plan": "plan", "synthesize": "synthesize"})
    return g.compile()


def compact(node: str, u: dict) -> dict:
    """Small, safe trace payload per node; never raw evidence text."""
    if node == "understand":
        x = u["understanding"]
        return {"intent": x.intent, "entities": x.entities}
    if node in ("seed", "retrieve"):
        return {"calls": u["done_calls"], "rejected": u["rejected"], "evidence_ids": list(u["evidence"]),
                "cypher": u["cypher"],
                **({"attempts": u["attempts"]} if "attempts" in u else {})}
    if node == "plan":
        return {"reasoning": u["plan"].reasoning, "calls": [f"{c.tool}({c.arg})" for c in u["plan"].calls]}
    if node == "evaluate":
        c = u["check"]
        return {"sufficient": c.sufficient, "relevant_ids": c.relevant_ids, "gap": c.gap}
    if node == "synthesize":
        return {"claims": len((u["answer"] or {}).get("claims") or [])}
    f = u["final"]
    return {"confidence": f["confidence"], "claims": len(f["claims"]),
            "supported": sum(c["status"] == "supported" for c in f["claims"])}


def _anchor(anchor: dict | None) -> dict | None:
    """{file, line, text, blame_id?} from the API layer; text is truncated, blame_id must look like an id."""
    if not anchor:
        return None
    blame = anchor.get("blame_id")
    return {"file": str(anchor["file"]), "line": int(anchor["line"]), "text": str(anchor.get("text") or "")[:300],
            "blame_id": blame if isinstance(blame, str) and ID_RE.fullmatch(blame) else None}


def stream(question: str, mode: str = "why", provider: str | None = None, model: str | None = None,
           driver=None, anchor: dict | None = None) -> Iterator[dict]:
    """Yield {event:trace,node,data,ms,update} per node, then {event:done,state,h,provider,model}; failures become one
    error event. `update` is the raw node output (the investigation assembler reads it)."""
    own = False
    try:
        if mode not in P.MODES:
            raise ValueError(f"unknown mode {mode!r}; choose one of {list(P.MODES)}")
        if not isinstance(question, str) or not question.strip() or len(question) > MAX_QUESTION:
            raise ValueError(f"question must be 1-{MAX_QUESTION} characters")
        anchor = _anchor(anchor)
        provider = provider or llm.default_provider()
        model = llm.model_for(provider, model)
        llm.client(provider)  # fail early if unconfigured
        from ..config import load_env, neo4j_driver
        from .harness import selfcheck

        if driver is None:
            load_env()
            driver, own = neo4j_driver(), True
        selfcheck(driver)
        def gen(q, err):
            hint = f"Your previous query failed: {err}\nFix it." if err else ""
            return llm.structured(provider, P.CYPHER_GEN, P.CypherOut, model, card=SCHEMA_CARD, question=q,
                                  error=hint).cypher

        h = Harness(driver, cypher_llm=gen)
        asked = question
        if anchor:
            asked += (f"\n\n(This question is about line {anchor['line']} of {anchor['file']}: {anchor['text']!r}."
                      + (f" That line was last changed by the evidence item {anchor['blame_id']}." if anchor["blame_id"] else "")
                      + ")")
        state: dict = {}
        t = time.perf_counter()
        for chunk in build(h, provider, model).stream({"question": asked, "mode": mode, "anchor": anchor},
                                                      stream_mode="updates"):
            for node, update in chunk.items():
                update, now = update or {}, time.perf_counter()
                state.update(update)
                yield {"event": "trace", "node": node, "data": compact(node, update), "ms": int((now - t) * 1000),
                       "update": update}
                t = time.perf_counter()
        yield {"event": "done", "state": state, "h": h, "provider": provider, "model": model}
    except Exception as error:  # noqa: BLE001
        own_msg = isinstance(error, (ValueError, RuntimeError))  # our messages; others may carry provider detail
        yield {"event": "error",
               "message": str(error)[:300] if own_msg else f"agent run failed ({type(error).__name__})"}
    finally:
        if own and driver is not None:
            driver.close()


def run(question: str, mode: str = "why", provider: str | None = None, model: str | None = None,
        driver=None, anchor: dict | None = None) -> Iterator[dict]:
    """Legacy event stream for /api/ask: trace events then one answer event derived from the verified claims."""
    for ev in stream(question, mode, provider, model, driver, anchor):
        if ev["event"] == "trace":
            yield {"event": "trace", "node": ev["node"], "data": ev["data"]}
        elif ev["event"] == "error":
            yield ev
        else:
            state, h = ev["state"], ev["h"]
            evidence, final = state["evidence"], state["final"]
            cited = [ci["node"] for c in final["claims"] for ci in c["cites"]]
            keep = [i for i in evidence if i in state["check"].relevant_ids or i in cited]
            keep = (keep or list(evidence))[:25]
            yield {"event": "answer",
                   "answer": {**to_legacy(final, evidence), "mode": mode, "provider": ev["provider"],
                              "model": ev["model"], "prompt_version": P.PROMPT_VERSION, "attempts": state["attempts"]},
                   "evidence": {"nodes": [evidence[i] for i in keep], "edges": h.edges_among(keep)}}
