import json
import re
import sys
import threading
import types
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from hackfront import config
from hackfront.api import app

client = TestClient(app)
ANSWER = {"event": "answer", "answer": {"answer": "x [u]", "citations": ["u"], "confidence": "high"},
          "evidence": {"nodes": [], "edges": []}}


def fake(monkeypatch, name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, mod)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_FILE", tmp_path / "workspace.json")


def events(text):
    out = []
    for block in text.strip().split("\n\n"):
        name, data = block.split("\n")
        out.append((name.removeprefix("event: "), json.loads(data.removeprefix("data: "))))
    return out


def test_status_never_leaks_tokens(monkeypatch):
    for k, v in {"GITHUB_TOKEN": "ghp_SECRET1", "JIRA_API_TOKEN": "jira_SECRET2", "JIRA_EMAIL": "a@b.c",
                 "SLACK_BOT_TOKEN": "xoxb-SECRET3"}.items():
        monkeypatch.setenv(k, v)
    fake(monkeypatch, "hackfront.ingest.sync", graph_counts=lambda: (_ for _ in ()).throw(RuntimeError("bolt://u:SECRET4@h")))
    fake(monkeypatch, "hackfront.agent", providers=lambda: [{"name": "p", "model": "m", "configured": True}])
    r = client.get("/api/status")
    assert r.status_code == 200
    assert "SECRET" not in r.text
    body = r.json()
    assert body["sources"]["github"]["token_present"] is True
    assert body["neo4j"]["ok"] is False and body["providers"][0]["name"] == "p"


def test_status_counts(monkeypatch):
    fake(monkeypatch, "hackfront.ingest.sync", graph_counts=lambda: {"artifacts": 3})
    assert client.get("/api/status").json()["neo4j"] == {"ok": True, "counts": {"artifacts": 3}}


def test_workspace_roundtrip_and_validation():
    assert client.get("/api/workspace").json()["github"]["repos"] == []
    ws = {"github": {"owner": "o", "repos": ["r"]}}
    assert client.put("/api/workspace", json=ws).json()["github"] == {"owner": "o", "repos": ["r"]}
    assert client.get("/api/workspace").json()["github"]["owner"] == "o"
    r = client.put("/api/workspace", json={"jira": {"site": "http://x", "projects": []}})
    assert r.status_code == 422 and "https" in r.json()["detail"]
    assert client.put("/api/workspace", json={"github": {"repos": "r"}}).status_code == 422


def test_ask_streams_trace_then_answer(monkeypatch):
    seen = {}

    def run(question, mode="why", provider=None, model=None):
        seen.update(question=question, mode=mode)
        yield {"event": "trace", "node": "plan", "data": {"n": 1}}
        yield ANSWER

    fake(monkeypatch, "hackfront.agent", run=run)
    r = client.post("/api/ask", json={"question": " why? ", "mode": "debug"})
    assert r.headers["content-type"].startswith("text/event-stream")
    assert [e for e, _ in events(r.text)] == ["trace", "answer"]
    assert seen == {"question": "why?", "mode": "debug"}


@pytest.mark.parametrize("body", [{"question": "q", "mode": "nope"}, {"question": "  ", "mode": "why"},
                                  {"question": "x" * 8001, "mode": "why"}, {"mode": "why"}])
def test_ask_rejects_invalid(body):
    assert client.post("/api/ask", json=body).status_code == 422


def test_ask_agent_error_is_safe(monkeypatch):
    def boom(*a, **k):
        yield {"event": "trace", "node": "n", "data": {}}
        raise RuntimeError("Traceback secret sk-123")

    fake(monkeypatch, "hackfront.agent", run=boom)
    r = client.post("/api/ask", json={"question": "q"})
    assert "sk-123" not in r.text and "Traceback" not in r.text
    assert events(r.text)[-1][0] == "error"

    fake(monkeypatch, "hackfront.agent", run=lambda *a, **k: iter([{"event": "error", "message": "no key"}]))
    assert events(client.post("/api/ask", json={"question": "q"}).text) == [("error", {"message": "no key"})]


def test_sync_409_while_running(monkeypatch):
    started, release = threading.Event(), threading.Event()

    def slow(ws, *, demo=False):
        started.set()
        release.wait(5)
        return [{"stream": "s"}]

    fake(monkeypatch, "hackfront.ingest.sync", sync_workspace=slow)
    fake(monkeypatch, "hackfront.ingest.demo", DEMO_WORKSPACE={})
    out = {}
    t = threading.Thread(target=lambda: out.update(r=client.post("/api/sync", json={"demo": False})))
    t.start()
    assert started.wait(5)
    assert client.post("/api/demo").status_code == 409
    release.set()
    t.join()
    assert out["r"].json() == {"summaries": [{"stream": "s"}]}
    assert client.post("/api/demo").status_code == 200


def test_sync_runtime_error_safe_message(monkeypatch):
    def bad(ws, *, demo=False):
        raise RuntimeError("Neo4j is not configured")

    fake(monkeypatch, "hackfront.ingest.sync", sync_workspace=bad)
    r = client.post("/api/sync", json={"demo": False})
    assert r.status_code == 500 and r.json()["detail"] == "Neo4j is not configured"


def test_web_files_offline():
    web = Path(__file__).resolve().parents[2] / "web"
    html = (web / "index.html").read_text(encoding="utf-8")
    assert "app.js" in html and "style.css" in html
    for f in ("index.html", "app.js", "style.css"):  # no remote loads (links to evidence are runtime data)
        assert not re.search(r"""(src|href)=["']https?:|url\(\s*["']?https?:|@import|fetch\(\s*["']https?:""",
                             (web / f).read_text(encoding="utf-8"))
    assert client.get("/").status_code == 200
