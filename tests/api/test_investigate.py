import json

import pytest
from fastapi.testclient import TestClient

from hackfront import config
from hackfront.api import app, investigate as route, workbench
from tests.agent.unit.conftest import Scripted, cid, fake, graph  # noqa: F401  (fixtures)

client = TestClient(app)
C1, PR, ISSUE = cid("commit", "c1"), cid("pull_request", "pr1"), cid("issue", "issue1")
ANSWER = {"summary": "Capped at 3 after an outage.", "gaps": ["No ADR."], "claims": [
    {"text": "The cap came from PAY-412.", "status": "supported", "cites": [{"id": PR, "quote": "Fixes PAY-412 retry storm."}]},
    {"text": "Is 3 still right?", "status": "unknown", "note": "No metrics.", "cites": []}]}


class Keep:
    """Driver proxy: the throwaway test driver is session-scoped, so close() must not close it."""

    def __init__(self, driver):
        self.driver = driver

    def __getattr__(self, name):
        return getattr(self.driver, name)

    def close(self):
        pass


@pytest.fixture
def env(graph, fake, tmp_path, monkeypatch):  # noqa: F811
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(config, "neo4j_driver", lambda: Keep(graph))
    fake(Scripted([{"tool": "find_text", "arg": "zzz"}], ANSWER))
    monkeypatch.setattr(workbench, "blame_for", lambda d, o, r, p: {
        "path": p, "complete": True, "lines": [{"text": "import time", "blame": C1}, {"text": "x = 1", "blame": C1},
                                               {"text": "MAX_RETRIES = 3", "blame": C1}]})
    monkeypatch.setattr(workbench, "_graph_scopes", lambda: {"indexed": ["acme/shop"]})
    return tmp_path


def events(text):
    out = []
    for block in text.strip().split("\n\n"):
        name, data = block.split("\n")
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def post(**body):
    return client.post("/api/investigate", json={"question": "Why is it 3?", "provider": "azure", **body})


def test_sse_trace_then_investigation_persisted_and_readable(env):
    r = post(file="src/pay/gateway.py", line=3)
    assert r.headers["content-type"].startswith("text/event-stream")
    evs = events(r.text)
    assert [e for e, _ in evs[:-1]] == ["trace"] * 7 and evs[-1][0] == "investigation"
    inv, graph_ = evs[-1][1]["investigation"], evs[-1][1]["graph"]
    assert [d["step"] for e, d in evs[:-1]] == inv["trace"] and inv["trace"][0]["kind"] == "understand"
    assert (inv["file"], inv["line"], inv["confidence"]) == ("src/pay/gateway.py", 3, "medium")
    assert [c["status"] for c in inv["claims"]] == ["supported", "unknown"]
    assert {n["id"] for n in graph_["nodes"]} == set(inv["nodes"]) and graph_["edges"]
    assert client.get("/api/investigations").json() == [
        {"id": inv["id"], "question": "Why is it 3?", "file": "src/pay/gateway.py", "line": 3,
         "confidence": "medium", "created_at": inv["created_at"]}]
    assert client.get(f"/api/investigations/{inv['id']}").json() == {"investigation": inv, "graph": graph_}


def test_unanchored_works_without_any_blame(env, monkeypatch):
    inv = events(post().text)[-1][1]["investigation"]
    assert "file" not in inv and [s["kind"] for s in inv["trace"]][:2] == ["understand", "plan"]


def test_anchor_failures_are_safe_http_errors(env, monkeypatch):
    def lookup(d, o, r, p):
        raise LookupError("secret internal path")

    monkeypatch.setattr(workbench, "blame_for", lookup)
    r = post(file="a.py", line=1)
    assert r.status_code == 404 and "secret" not in r.text
    monkeypatch.setattr(workbench, "blame_for", lambda d, o, r, p: 1 / 0)
    assert post(file="a.py", line=1).status_code == 422
    monkeypatch.setattr(workbench, "blame_for", lambda d, o, r, p: {"complete": False, "note": "patch missing", "lines": []})
    r = post(file="a.py", line=1)
    assert r.status_code == 422 and "patch missing" in r.text  # incomplete blame is never guessed around
    monkeypatch.setattr(workbench, "blame_for", lambda d, o, r, p: {"complete": True, "lines": [{"text": "x", "blame": C1}]})
    assert post(file="a.py", line=9).status_code == 404  # line beyond the file
    monkeypatch.setattr(workbench, "_graph_scopes", lambda: {"indexed": ["a/b", "c/d"]})
    assert post(file="a.py", line=1).status_code == 422  # ambiguous repo needs `repo`
    assert client.get("/api/investigations").json() == []  # nothing persisted on failure


@pytest.mark.parametrize("body", [
    {"question": "  "}, {"question": "x" * 8001}, {"mode": "nope"}, {"provider": "nope"}, {"model": "a b;"},
    {"file": "a.py"}, {"line": 3}, {"file": "../a.py", "line": 1}, {"file": "/etc/passwd", "line": 1},
    {"file": "a\\b.py", "line": 1}, {"file": "a//b.py", "line": 1}, {"file": "C:/a.py", "line": 1},
    {"file": "a.py", "line": 0}, {"file": "a.py", "line": -2}, {"file": "a.py", "line": "3"}, {"file": "a.py", "line": True},
])
def test_validation_rejects(env, body):
    assert post(**body).status_code == 422


def test_missing_question_and_wrong_types_422(env):
    assert client.post("/api/investigate", json={"mode": "why"}).status_code == 422
    assert client.post("/api/investigate", json={"question": 5}).status_code == 422


def test_at_most_three_concurrent(env):
    held = [route._slots.acquire(blocking=False) for _ in range(3)]
    try:
        r = post()
        assert r.status_code == 429 and "At most 3" in r.json()["detail"]
    finally:
        for _ in held:
            route._slots.release()
    assert events(post().text)[-1][0] == "investigation"  # slot freed again, and after a normal run too
    assert all(route._slots.acquire(blocking=False) for _ in range(3))
    for _ in range(3):
        route._slots.release()


def test_errors_are_safe_events_and_nothing_persisted(env, monkeypatch):
    r = client.post("/api/investigate", json={"question": "q", "provider": "sarvam"})  # not configured in tests
    assert events(r.text)[-1][0] == "error" and "SARVAM_API_KEY" in r.text

    def boom(*a, **k):
        yield {"event": "trace", "step": {"kind": "plan"}}
        raise RuntimeError("Traceback secret sk-123")

    monkeypatch.setattr("hackfront.agent.investigation.investigate", boom)
    r = post()
    assert "sk-123" not in r.text and "Traceback" not in r.text and events(r.text)[-1][0] == "error"
    assert client.get("/api/investigations").json() == []
    assert all(route._slots.acquire(blocking=False) for _ in range(3))  # slots released after failures
    for _ in range(3):
        route._slots.release()


def test_get_rejects_unknown_and_traversal(env):
    (env / "secret.json").write_text(json.dumps({"investigation": {"id": "x"}, "graph": {}}))
    for bad in ("nope", "..%2Fsecret", "..%2F..%2Fsecret", "secret.json", "UPPER", "x" * 81):
        assert client.get(f"/api/investigations/{bad}").status_code == 404
