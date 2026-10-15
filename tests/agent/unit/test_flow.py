import json

import pytest

from hackfront import agent
from hackfront.agent import llm

from .conftest import cid, url


class Scripted:
    """Fake OpenAI client: answers by the schema title found in the prompt."""

    def __init__(self, plan_calls, answer=None):
        self.plan_calls, self.answer, self.seen = plan_calls, answer, []
        self.chat = self
        self.completions = self

    def create(self, model, messages, max_tokens):
        prompt = messages[0]["content"]
        title = json.loads(prompt.split("matching this JSON Schema:\n")[-1])["title"]
        self.seen.append(title)
        out = {
            "Understanding": {"intent": "why cap", "entities": ["PAY-412"], "time_hint": None},
            "Plan": {"reasoning": "start", "calls": self.plan_calls},
            "Sufficiency": {"sufficient": True, "relevant_ids": [cid("pull_request", "pr1"), cid("issue", "issue1")], "gap": ""},
            "Answer": self.answer,
            "CypherOut": {"cypher": "MATCH (i:Artifact {record_kind:'issue'}) RETURN i"},
        }[title]
        msg = type("M", (), {"content": json.dumps(out)})
        return type("R", (), {"choices": [type("C", (), {"message": msg})]})


@pytest.fixture
def fake(monkeypatch):
    def install(f):
        monkeypatch.setattr(llm, "_clients", {"azure": f})
        return f
    return install


def collect(graph, q, **kw):
    return list(agent.run(q, provider="azure", driver=graph, **kw))


def test_full_flow_trace_then_one_verified_answer(graph, fake):
    pr = cid("pull_request", "pr1")
    f = fake(Scripted(
        [{"tool": "find_text", "arg": "PAY-412 storm"}, {"tool": "evidence_chain", "arg": pr},
         {"tool": "neighbors", "arg": "github:acme:issue:hallucinated"},
         {"tool": "cypher_query", "arg": "issues about retries"}],
        {"answer": f"Capped at 3 after an outage [{url('issue', 'issue1')}] [https://evil/1].",
         "citations": [url("issue", "issue1"), "https://evil/1"], "confidence": "high", "uncertainty": ""}))
    events = collect(graph, "Why are gateway retries capped at 3?")
    assert [e["event"] for e in events] == ["trace"] * 7 + ["answer"]
    assert [e["node"] for e in events[:-1]] == ["understand", "seed", "plan", "retrieve", "evaluate", "synthesize", "verify"]
    retrieve = next(e for e in events if e.get("node") == "retrieve")["data"]
    assert any("hallucinated" in r for r in retrieve["rejected"]) and pr in retrieve["evidence_ids"]
    assert retrieve["cypher"][0]["cypher"].endswith("LIMIT 25"), retrieve["cypher"]
    a = events[-1]["answer"]
    assert a["citations"] == [url("issue", "issue1")] and "evil" not in a["answer"] and a["confidence"] == "low"
    assert (a["mode"], a["provider"], a["prompt_version"], a["attempts"]) == ("why", "azure", "v3", 1)
    ids = {n["id"] for n in events[-1]["evidence"]["nodes"]}
    assert {pr, cid("issue", "issue1")} <= ids and events[-1]["evidence"]["edges"]
    assert f.seen.count("CypherOut") == 1


def test_no_evidence_short_circuits_without_synthesis(graph, fake):
    f = fake(Scripted([{"tool": "find_text", "arg": "zzz qqq"}], answer=None))
    events = collect(graph, "what about the zzz qqq module?")
    a = events[-1]["answer"]
    assert a["answer"].startswith("Not established") and a["citations"] == [] and a["confidence"] == "low"
    assert "Answer" not in f.seen and events[-1]["evidence"] == {"nodes": [], "edges": []}


def test_debug_mode_seeds_run_before_planning(graph, fake):
    fake(Scripted([{"tool": "find_text", "arg": "PAY-412"}], {"answer": f"see [{url('commit', 'c1')}]",
          "citations": [url("commit", "c1")], "confidence": "medium", "uncertainty": "x"}))
    events = collect(graph, 'File "/srv/src/pay/gateway.py", line 3\nError PAY-412', mode="debug")
    seed = next(e for e in events if e.get("node") == "seed")["data"]
    assert seed["calls"] == ["file_history(src/pay/gateway.py)", "find_text(PAY-412)"]
    assert cid("commit", "c1") in seed["evidence_ids"]
    assert events[-1]["answer"]["mode"] == "debug"


def test_errors_are_events_not_exceptions(graph):
    assert collect(graph, "q", mode="bogus")[0]["event"] == "error"
    assert list(agent.run("q", provider="nope", driver=graph))[0]["event"] == "error"
    ev = list(agent.run("q", provider="sarvam", driver=graph))[0]  # not configured in test env
    assert ev["event"] == "error" and "SARVAM_API_KEY" in ev["message"]
    assert collect(graph, " ")[0]["event"] == "error"
