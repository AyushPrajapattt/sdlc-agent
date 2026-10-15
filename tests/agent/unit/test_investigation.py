import json

import pytest

from hackfront import config
from hackfront.agent import investigation as inv
from hackfront.ingest.contracts import Provenance, RecordKind, SourceIdentity, Artifact
from hackfront.ingest.storage.neo4j import Neo4jStore

from .conftest import K, Scripted, art, cid, url

C1, PR, ISSUE = cid("commit", "c1"), cid("pull_request", "pr1"), cid("issue", "issue1")
ANCHOR = {"file": "src/pay/gateway.py", "line": 3, "text": "MAX_RETRIES = 3", "blame_id": C1}


def synth(*claims, gaps=("No ADR ingested.",)):
    return {"summary": "Capped at 3 after an outage.", "claims": list(claims), "gaps": list(gaps)}


CLAIMS = (
    {"text": "The cap came from PAY-412.", "status": "supported",
     "cites": [{"id": PR, "quote": "Fixes PAY-412 retry storm."}, {"id": C1}]},
    {"text": "It was likely set to protect the gateway.", "status": "inferred", "note": "No source says so.",
     "cites": [{"id": ISSUE, "quote": "gateway retries caused the outage"}]},
    {"text": "Whether 3 is still right.", "status": "unknown", "note": "No metrics ingested.", "cites": []},
)


def run(graph, fake, answer=None, anchor=ANCHOR, find="zzz", **kw):
    fake(Scripted([{"tool": "find_text", "arg": find}], answer or synth(*CLAIMS), **kw))
    events = list(inv.investigate("Why is it 3?", "why", "azure", None, graph, anchor))
    assert events[-1]["event"] == "investigation", events[-1]
    return events, events[-1]["investigation"], events[-1]["graph"]


def test_steps_afterstep_excluded_graph(graph, fake):
    events, i, g = run(graph, fake)
    assert [s["kind"] for s in i["trace"]] == ["understand", "tool", "tool", "plan", "tool", "gap", "synthesize"]
    assert [e["step"] for e in events if e["event"] == "trace"] == i["trace"]  # streamed == stored
    tool = [s for s in i["trace"] if s["kind"] == "tool"]
    assert tool[0]["label"] == 'file_history("src/pay/gateway.py")' and tool[0]["detail"] == "2 rows"
    assert tool[1]["label"] == f'evidence_chain("{C1}")' and tool[2]["detail"] == "0 rows"
    assert i["trace"][0]["detail"].startswith("Anchor src/pay/gateway.py:3 · intent:")
    assert i["trace"][-1]["detail"] == "3 claims · 1 supported · 1 inferred · 1 unknown"
    assert all(isinstance(s["ms"], int) and s["ms"] >= 0 for s in i["trace"])
    # claim ids, afterStep = first step that surfaced all cited nodes; no cites -> the gap step
    assert [c["id"] for c in i["claims"]] == ["c1", "c2", "c3"]
    assert [c["afterStep"] for c in i["claims"]] == [2, 2, 5] and "note" not in i["claims"][0]
    assert i["claims"][0]["cites"][0] == {"node": PR, "quote": "Fixes PAY-412 retry storm."}
    assert (i["file"], i["line"], i["mode"], i["prompt_version"], i["provider"]) == (ANCHOR["file"], 3, "why", "v4", "azure")
    assert i["nodes"][:3] == [PR, C1, ISSUE] and set(i["nodes"]) == {r["id"] for r in g["nodes"]}
    # excluded: c2 and thread1 are linked to cited nodes; msg1 only reaches thread1 (not cited), issue2 only via a stub
    reasons = {e["node"]: e["reason"] for e in i["excluded"]}
    assert reasons == {cid("commit", "c2"): inv.LINKED, cid("thread", "thread1"): inv.LINKED,
                       cid("message", "msg1"): inv.KEYWORD_ONLY, cid("issue", "issue2"): inv.KEYWORD_ONLY}
    assert i["confidence"] == "medium" and i["gaps"] == ["No ADR ingested."] and i["id"].endswith(i["id"][-6:])
    assert inv.ID_OK.fullmatch(i["id"]) and g["edges"]


def test_checks_later_commits_and_jira_status(graph, fake):
    store = Neo4jStore(graph)
    store.write_artifact(art("commit", "c3", K.GIT_COMMIT, "refactor retry", "later", "2024-03-01T00:00:00Z", ["src/pay/gateway.py"]))
    jira = Artifact(source=SourceIdentity("jira", "PAY", "issue", "PAY-9", "https://j.test/PAY-9"), kind=K.ISSUE,
                    observed_at="2024-06-01T00:00:00Z", event_time="2024-01-01T00:00:00Z", title="PAY-9", text="x",
                    raw_payload={}, context={"status": "Done"},
                    provenance=Provenance("https://j.test/PAY-9", "$", "2024-06-01T00:00:00Z", "t/1"))
    store.write_artifact(jira)
    jid = jira.source.canonical_id
    claims = (CLAIMS[0], {"text": "Tracked in Jira.", "status": "supported", "cites": [{"id": jid}]})
    _, i, _ = run(graph, fake, synth(*claims), find="PAY-9", relevant=[PR, jid, C1])
    by = {c["label"]: c for c in i["checks"]}
    later = by["Later commits touching src/pay/gateway.py"]
    assert later["state"] == "changed" and "c3" in later["detail"] and "refactor retry" in later["detail"]
    assert by["PAY-9 status"] == {"label": "PAY-9 status", "state": "unknown", "detail": "Jira status: Done (as of last sync)"}


def test_checks_holds_when_nothing_later(graph, fake):
    _, i, _ = run(graph, fake)
    assert i["checks"] == [{"label": "Later commits touching src/pay/gateway.py", "state": "holds",
                            "detail": "0 commits after 2024-02-01."}]


def test_unanchored_has_no_file_check_and_no_evidence_is_fixed(graph, fake):
    _, i, _ = run(graph, fake, anchor=None)
    assert "file" not in i and i["checks"] == []
    fake(Scripted([{"tool": "find_text", "arg": "zzz qqq"}]))
    out = list(inv.investigate("nothing here", "why", "azure", None, graph))[-1]["investigation"]
    assert out["summary"].startswith("Not established") and out["confidence"] == "low"
    assert [c["status"] for c in out["claims"]] == ["unknown"] and out["claims"][0]["cites"] == []
    assert out["nodes"] == [] and out["excluded"] == [] and out["trace"][-1]["kind"] == "synthesize"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    return tmp_path


def test_persistence_roundtrip_listing_and_traversal(home):
    a = {"id": inv.new_id("Why is the TTL 15 min?!"), "question": "q1", "confidence": "low", "created_at": "2026-01-01T00:00:00Z"}
    b = {"id": inv.new_id("")[:20], "question": "q2", "file": "f.py", "line": 2, "confidence": "high", "created_at": "2026-02-01T00:00:00Z"}
    assert a["id"].startswith("why-is-the-ttl-15-min-") and inv.ID_OK.fullmatch(a["id"])
    inv.save(a, {"nodes": [], "edges": []})
    inv.save(b, {"nodes": [{"id": "n"}], "edges": []})
    assert inv.get(a["id"]) == {"investigation": a, "graph": {"nodes": [], "edges": []}}
    assert [r["id"] for r in inv.list_all()] == [b["id"], a["id"]] and inv.list_all()[0]["line"] == 2
    assert not list((home / ".hackfront" / "investigations").glob("*.tmp"))
    (home / "secret.json").write_text(json.dumps({"investigation": "x"}))
    for bad in ("../../secret", "..\\secret", "../secret", "A", "a/b", "", "x" * 81, "a.json"):
        assert inv.get(bad) is None
    with pytest.raises(ValueError):
        inv.save({**a, "id": "../evil"}, {})
    assert inv.list_all(limit=1)[0]["id"] in (a["id"], b["id"])
