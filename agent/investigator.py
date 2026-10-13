r"""LangGraph investigation agent over the Neo4j engineering-memory graph.

Flow: understand -> plan -> retrieve -> evaluate -(insufficient & attempts left)-> plan
                                               \-(sufficient | max attempts)--> synthesize

Usage:
    pip install langgraph openai pydantic          (+ neo4j when AGENT_GRAPH=neo4j)
    set AZURE_FOUNDRY_ENDPOINT   e.g. https://<resource>.services.ai.azure.com/openai/v1/
        AZURE_FOUNDRY_API_KEY
        AGENT_MODEL              Foundry deployment name, default Kimi-K2.5
        AGENT_GRAPH              mock (default, agent/mock_graph.py) | neo4j (+ NEO4J_URI/USERNAME/PASSWORD)
    python agent/investigator.py "Why are gateway retries capped at 3?"
"""

from __future__ import annotations

import json
import operator
import os
import sys
from typing import Annotated, TypedDict
from urllib.parse import urlsplit

from langgraph.graph import END, StateGraph
from openai import OpenAI
from pydantic import ValidationError

import prompts as P

MODEL = os.environ.get("AGENT_MODEL", "Kimi-K2.5")
MAX_ATTEMPTS = int(os.environ.get("AGENT_MAX_ATTEMPTS", "3"))
ROW_LIMIT = 10

def foundry_base_url(endpoint: str) -> str:
    """Any URL Foundry shows (project, /models, /openai/deployments/...?api-version=) -> <resource root>/openai/v1/."""
    parts = urlsplit(endpoint.strip())
    if parts.netloc.endswith(".models.ai.azure.com"):  # serverless (pay-as-you-go) endpoint
        return f"{parts.scheme}://{parts.netloc}/v1/"
    return f"{parts.scheme}://{parts.netloc}/openai/v1/"


# Foundry serves non-OpenAI models (Kimi included) on an OpenAI-compatible /openai/v1 endpoint.
# Azure key auth reads the `api-key` header; the SDK only sends `Authorization: Bearer`, so send both.
_key = os.environ["AZURE_FOUNDRY_API_KEY"].strip()
llm = OpenAI(base_url=foundry_base_url(os.environ["AZURE_FOUNDRY_ENDPOINT"]), api_key=_key,
             default_headers={"api-key": _key})


def ask(template: str, schema, **fields):
    """One structured LLM call; returns a validated pydantic instance.

    Schema goes in the prompt and output is validated locally, so this doesn't depend on
    Foundry's json_schema support for Kimi. One repair round-trip on invalid JSON.
    """
    messages = [{"role": "user", "content": template.format(**fields)
                 + "\n\nRespond with ONLY a JSON object (no prose, no code fences) matching this JSON Schema:\n"
                 + json.dumps(schema.model_json_schema())}]
    for _ in range(2):
        text = llm.chat.completions.create(model=MODEL, messages=messages, max_tokens=16000) \
                  .choices[0].message.content or ""
        try:
            return schema.model_validate_json(text[text.find("{"): text.rfind("}") + 1])
        except ValidationError as error:
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"That JSON was invalid: {error}. Return the corrected JSON only."}]
    raise RuntimeError(f"{MODEL} did not return valid {schema.__name__}: {text[:500]}")


# --- 4. Python layer: graph retrieval tools (read-only Cypher) ----------------------

_RETURN = """RETURN DISTINCT a.canonical_id AS id, a.record_kind AS kind, a.title AS title,
       left(coalesce(a.text, ''), 600) AS text, a.source_uri AS url,
       a.event_time AS time, a.change_paths AS paths
LIMIT $limit"""

CYPHER = {
    "search_text": "MATCH (a:Artifact) WHERE toLower(coalesce(a.title,'') + ' ' + coalesce(a.text,'')) "
                   "CONTAINS toLower($arg) " + _RETURN,
    "search_path": "MATCH (a:Artifact) WHERE any(p IN coalesce(a.change_paths, []) WHERE p CONTAINS $arg) "
                   + _RETURN,
    # ponytail: 1-hop only; planner chains hops across attempts. Use variable-length paths if that proves slow.
    "expand": "MATCH (:Artifact {canonical_id: $arg})-[]-(a:Artifact) " + _RETURN,
}


if os.environ.get("AGENT_GRAPH", "mock") == "neo4j":
    from neo4j import GraphDatabase

    db = GraphDatabase.driver(
        os.environ["NEO4J_URI"], auth=(os.environ["NEO4J_USERNAME"], os.environ["NEO4J_PASSWORD"])
    )
    DATABASE = os.environ.get("NEO4J_DATABASE", "neo4j")

    def run_tool(call: P.ToolCall) -> list[dict]:
        records, _, _ = db.execute_query(
            CYPHER[call.tool], arg=call.arg, limit=ROW_LIMIT, database_=DATABASE, routing_="r"
        )
        return [r.data() for r in records]
else:
    from mock_graph import run_tool  # same row shape as the Cypher RETURN above


# --- State ----------------------------------------------------------------------------

class State(TypedDict, total=False):
    question: str
    understanding: P.Understanding
    plan: P.Plan
    done_calls: Annotated[list[str], operator.add]
    evidence: dict[str, dict]
    attempts: int
    check: P.Sufficiency # bool
    answer: P.Answer


def render(evidence: dict[str, dict]) -> str:
    if not evidence:
        return "(none)"
    return "\n".join(
        f"- [{e['id']}] {e['kind']} {e.get('time') or ''} {e.get('url') or ''}\n"
        f"  title: {e.get('title') or ''}\n  paths: {e.get('paths') or ''}\n  text: {e.get('text') or ''}"
        for e in evidence.values()
    )


# --- Nodes ------------------------------------------------------------------------------

def understand(s: State) -> State:  # 2
    return {"understanding": ask(P.UNDERSTAND, P.Understanding, question=s["question"]),
            "attempts": 0, "evidence": {}}


def plan(s: State) -> State:  # 3
    u, check = s["understanding"], s.get("check")
    p = ask(P.PLAN, P.Plan, intent=u.intent, entities=u.entities,
            attempt=s["attempts"] + 1, max_attempts=MAX_ATTEMPTS,
            done_calls=s.get("done_calls") or "(none)", evidence=render(s["evidence"]),
            gap=check.gap if check else "(first attempt)")
    return {"plan": p}


def retrieve(s: State) -> State:  # 4 -> 5
    evidence = dict(s["evidence"])
    done = []
    for call in s["plan"].calls:
        key = f"{call.tool}({call.arg})"
        if key in (s.get("done_calls") or []):
            continue
        done.append(key)
        for row in run_tool(call):
            evidence.setdefault(row["id"], row)
    return {"evidence": evidence, "done_calls": done, "attempts": s["attempts"] + 1}


def evaluate(s: State) -> State:  # 6/7
    check = ask(P.SUFFICIENCY, P.Sufficiency, question=s["question"], evidence=render(s["evidence"]))
    return {"check": check}

# state change condition: if check.sufficient or attempts >= MAX_ATTEMPTS, go to synthesize; else go to plan
def route(s: State) -> str:  # 8
    return "synthesize" if s["check"].sufficient or s["attempts"] >= MAX_ATTEMPTS else "plan"

# final call: synthesize the answer from the evidence, with citations and confidence/uncertainty
def synthesize(s: State) -> State:  # 9
    check = s["check"]
    relevant = {i: s["evidence"][i] for i in check.relevant_ids if i in s["evidence"]} or s["evidence"]
    return {"answer": ask(P.SYNTHESIZE, P.Answer, question=s["question"],
                          sufficient=check.sufficient, evidence=render(relevant))}


g = StateGraph(State)
for name, fn in [("understand", understand), ("plan", plan), ("retrieve", retrieve),
                 ("evaluate", evaluate), ("synthesize", synthesize)]:
    g.add_node(name, fn)
g.set_entry_point("understand")
g.add_edge("understand", "plan")
# How to handle the case where plan returns no calls? For now, let retrieve handle it and return an empty evidence set.
# How to handle cases where plan has bad queries?
g.add_edge("plan", "retrieve") 
g.add_edge("retrieve", "evaluate")
g.add_conditional_edges("evaluate", route, {"plan": "plan", "synthesize": "synthesize"})
g.add_edge("synthesize", END)
app = g.compile()


if __name__ == "__main__":
    # route self-check: loop while insufficient, stop on sufficient or at the attempt cap
    no = P.Sufficiency(sufficient=False, relevant_ids=[], gap="x")
    assert route({"check": no, "attempts": 1}) == "plan"
    assert route({"check": no, "attempts": MAX_ATTEMPTS}) == "synthesize"
    assert route({"check": no.model_copy(update={"sufficient": True}), "attempts": 1}) == "synthesize"
    for url in ("https://r.services.ai.azure.com/api/projects/p", "https://r.services.ai.azure.com/models",
                "https://r.services.ai.azure.com/openai/deployments/Kimi-K2.5/chat/completions?api-version=2024-05-01-preview"):
        assert foundry_base_url(url) == "https://r.services.ai.azure.com/openai/v1/", url

    if len(sys.argv) < 2:
        sys.exit(__doc__)
    # Trace each node as it finishes (stderr, so stdout stays just the answer).
    for mode, chunk in app.stream({"question": " ".join(sys.argv[1:])}, stream_mode=["updates", "values"]):
        if mode == "values":
            final = chunk  # 10
            continue
        for node, update in chunk.items():
            print(f"\n=== {node} ===", file=sys.stderr)
            for field, value in (update or {}).items():
                if field == "evidence":
                    value = f"{len(value)} items: {list(value)}"
                elif hasattr(value, "model_dump_json"):
                    value = value.model_dump_json(indent=2)
                print(f"{field}: {value}", file=sys.stderr)
    print()
    a = final["answer"]
    print(f"{a.answer}\n\nconfidence: {a.confidence}\nuncertainty: {a.uncertainty or '-'}")
    print("sources:\n" + "\n".join(f"  {c}" for c in a.citations))
    print(f"(attempts={final['attempts']}, prompts={P.PROMPT_VERSION}, model={MODEL})")
