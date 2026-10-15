from hackfront import agent

from .conftest import Scripted, cid, url


def collect(graph, q, **kw):
    return list(agent.run(q, provider="azure", driver=graph, **kw))


def synth(*claims, summary="Capped at 3 after an outage.", gaps=()):
    return {"summary": summary, "claims": list(claims), "gaps": list(gaps)}


def test_full_flow_trace_then_one_verified_answer(graph, fake):
    pr, issue = cid("pull_request", "pr1"), cid("issue", "issue1")
    f = fake(Scripted(
        [{"tool": "find_text", "arg": "PAY-412 storm"}, {"tool": "evidence_chain", "arg": pr},
         {"tool": "neighbors", "arg": "github:acme:issue:hallucinated"},
         {"tool": "cypher_query", "arg": "issues about retries"}],
        synth({"text": "Retries caused the outage.", "status": "supported",
               "cites": [{"id": issue, "quote": "gateway retries caused the outage"}, {"id": "github:acme:issue:fake", "quote": "x"}]},
              summary="Capped at 3 [https://evil/1].")))
    events = collect(graph, "Why are gateway retries capped at 3?")
    assert [e["event"] for e in events] == ["trace"] * 7 + ["answer"]
    assert [e["node"] for e in events[:-1]] == ["understand", "seed", "plan", "retrieve", "evaluate", "synthesize", "verify"]
    retrieve = next(e for e in events if e.get("node") == "retrieve")["data"]
    assert any("hallucinated" in r for r in retrieve["rejected"]) and pr in retrieve["evidence_ids"]
    assert retrieve["cypher"][0]["cypher"].endswith("LIMIT 25"), retrieve["cypher"]
    a = events[-1]["answer"]  # legacy shape for /api/ask, derived from the verified claims
    assert a["citations"] == [url("issue", "issue1")] and "evil" not in a["answer"] and a["confidence"] == "low"
    assert (a["mode"], a["provider"], a["prompt_version"], a["attempts"]) == ("why", "azure", "v4", 1)
    ids = {n["id"] for n in events[-1]["evidence"]["nodes"]}
    assert {pr, issue} <= ids and events[-1]["evidence"]["edges"]
    assert f.seen.count("CypherOut") == 1


def test_no_evidence_short_circuits_without_synthesis(graph, fake):
    f = fake(Scripted([{"tool": "find_text", "arg": "zzz qqq"}], answer=None))
    events = collect(graph, "what about the zzz qqq module?")
    a = events[-1]["answer"]
    assert a["answer"].startswith("Not established") and a["citations"] == [] and a["confidence"] == "low"
    assert "Synthesis" not in f.seen and events[-1]["evidence"] == {"nodes": [], "edges": []}


def test_debug_mode_seeds_run_before_planning(graph, fake):
    fake(Scripted([{"tool": "find_text", "arg": "PAY-412"}],
                  synth({"text": "c1 touched it", "status": "supported", "cites": [{"id": cid("commit", "c1")}]})))
    events = collect(graph, 'File "/srv/src/pay/gateway.py", line 3\nError PAY-412', mode="debug")
    seed = next(e for e in events if e.get("node") == "seed")["data"]
    assert seed["calls"] == ["file_history(src/pay/gateway.py)", "find_text(PAY-412)"]
    assert cid("commit", "c1") in seed["evidence_ids"]
    assert events[-1]["answer"]["mode"] == "debug"


def test_anchor_seeds_file_history_and_blame_chain_and_reaches_planner(graph, fake):
    c1 = cid("commit", "c1")
    f = fake(Scripted([{"tool": "find_text", "arg": "zzz"}], synth()))
    anchor = {"file": "src/pay/gateway.py", "line": 3, "text": "MAX_RETRIES = 3", "blame_id": c1}
    events = collect(graph, "why is this 3?", anchor=anchor)
    seed = next(e for e in events if e.get("node") == "seed")["data"]
    assert seed["calls"] == ["file_history(src/pay/gateway.py)", f"evidence_chain({c1})"] and not seed["rejected"]
    assert {c1, cid("pull_request", "pr1"), cid("issue", "issue1")} <= set(seed["evidence_ids"])
    assert any("line 3 of src/pay/gateway.py" in m for m in f.prompts)


def test_errors_are_events_not_exceptions(graph):
    assert collect(graph, "q", mode="bogus")[0]["event"] == "error"
    assert list(agent.run("q", provider="nope", driver=graph))[0]["event"] == "error"
    ev = list(agent.run("q", provider="sarvam", driver=graph))[0]  # not configured in test env
    assert ev["event"] == "error" and "SARVAM_API_KEY" in ev["message"]
    assert collect(graph, " ")[0]["event"] == "error"
