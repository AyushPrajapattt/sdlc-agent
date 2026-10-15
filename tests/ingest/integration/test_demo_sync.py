"""Background sync job: demo workspace through the real clients, live progress, scope, credentials, API."""

import json
import threading
import time

import pytest
from fastapi.testclient import TestClient

from hackfront import config
from hackfront.ingest import sync
from hackfront.ingest.demo import DEMO_WORKSPACE, SLACK_USERS, demo_clients
from hackfront.ingest.storage.neo4j import Neo4jStore

PR218 = "github:acme-demo%2Fshop:pull_request:218"
PAY412 = "jira:PAY:issue:PAY-412"


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    for key in ("GITHUB_TOKEN", "JIRA_EMAIL", "JIRA_API_TOKEN", "SLACK_BOT_TOKEN"):
        monkeypatch.delenv(key, raising=False)
    sync._jobs.clear()
    yield tmp_path
    sync._jobs.clear()


@pytest.fixture
def db(clean_graph, monkeypatch):
    from tests.conftest import TEST_AUTH, TEST_URI

    monkeypatch.setenv("NEO4J_URI", TEST_URI)
    monkeypatch.setenv("NEO4J_USERNAME", TEST_AUTH[0])
    monkeypatch.setenv("NEO4J_PASSWORD", TEST_AUTH[1])
    return clean_graph


def demo_workspace(slug="demo"):
    config.create_workspace("Acme Demo", demo=True, slug=slug)
    config.save_workspace(slug, DEMO_WORKSPACE)
    return slug


def wait(slug, timeout=60):
    end = time.time() + timeout
    while time.time() < end:
        status = sync.sync_status(slug)
        if status["state"] != "running":
            return status
        time.sleep(0.05)
    raise AssertionError("sync did not finish")


def _edges(driver):
    records, _, _ = driver.execute_query(
        "MATCH (a:Artifact)-[r]->(b:Artifact) RETURN a.canonical_id AS a, type(r) AS t, r.origin AS o, b.canonical_id AS b")
    return {(r["a"], r["t"], r["o"], r["b"]) for r in records}


# ---------------------------------------------------------------- no database needed
def test_start_sync_validation(home):
    with pytest.raises(LookupError):
        sync.start_sync("nope")
    slug = config.create_workspace("Empty")
    with pytest.raises(ValueError, match="no sources configured"):
        sync.start_sync(slug)
    with pytest.raises(ValueError, match="mode"):
        sync.start_sync(slug, "huge")
    assert sync.sync_status(slug)["state"] == "idle"


def test_interrupted_running_status_is_failed(home):
    slug = config.create_workspace("Crashy")
    stale = {"state": "running", "mode": "deep", "streams": [
        {"stream": "github:a/b:commits", "status": "running", "pages": 1, "fetched": 30, "persisted": 12, "errors": []}]}
    (config.workspace_dir(slug) / "sync.json").write_text(json.dumps(stale), encoding="utf-8")
    status = sync.sync_status(slug)
    assert status["state"] == "failed" and status["error"] == "interrupted" and status["mode"] == "deep"
    assert status["streams"][0]["status"] == "failed" and status["totals"]["persisted"] == 12


def test_demo_discovery_routes_through_real_clients():
    gh, jira, slack = demo_clients()
    assert gh.whoami() == "acme-demo-bot"
    assert gh.list_repos("acme-demo") == [{"full_name": "acme-demo/shop", "private": False}]
    assert gh.list_repos(None)[0]["full_name"] == "acme-demo/shop"
    assert jira.myself()["displayName"] and [p["key"] for p in jira.projects()] == ["PAY", "SEC"]
    assert slack.auth_test() == {"user": "hackfront-bot", "team": "acme-demo"}
    assert {c["name"] for c in slack.channels()} == {"payments-incident", "support", "eng-general"}
    assert slack.users() == SLACK_USERS


def test_learn_slack_names_merges_without_losing_fields(home):
    slug = config.create_workspace("Names")
    config.save_workspace(slug, {**config.load_workspace(slug), "github": {"owner": "o", "repos": ["r"]},
                                 "slack": {"workspace": "w", "channels": ["C01PAY"], "users": {"U_OLD": "old"}}})
    sync._learn_slack_names(slug, demo_clients()[2], ["C01PAY"])
    ws = config.load_workspace(slug)
    assert ws["slack"]["users"] == {"U_OLD": "old", **SLACK_USERS}
    assert ws["slack"]["channel_names"] == {"C01PAY": "payments-incident"}  # only configured channels
    assert ws["github"] == {"owner": "o", "repos": ["r"]} and ws["slack"]["workspace"] == "w"


# ---------------------------------------------------------------- Neo4j test database
def test_demo_chain_scope_and_idempotency(home, db, monkeypatch):
    slug = demo_workspace()
    assert sync.start_sync(slug)["state"] == "running"
    first = wait(slug)
    assert first["state"] == "done" and first["complete"], first
    assert all(s["status"] == "done" and not s["errors"] for s in first["streams"])
    assert {s["stream"] for s in first["streams"]} >= {
        "github:acme-demo/shop:commits", "github:acme-demo/shop:pulls", "github:acme-demo/shop:pr_activity",
        "jira:PAY:issues", "jira:PAY:comments", "slack:C01PAY:history", "slack:C01PAY:replies"}
    assert first["totals"]["persisted"] == first["totals"]["fetched"] > 0 and first["totals"]["errors"] == 0
    graph, edges = first["graph"], _edges(db)
    assert graph["artifacts"] > 0 and graph["edges"] >= len(edges) and graph["stubs"] >= 0

    commit_ids = {b for a, t, o, b in edges if a == PR218 and t == "CONTAINS" and o == "structural"}
    assert len(commit_ids) >= 2  # PR -> its commits (from the PR commits endpoint)
    slack_thread = "slack:acme-demo:thread:" + next(
        b.split(":")[-1] for a, t, o, b in edges if a == PR218 and o == "text" and ":thread:" in b)
    assert (PR218, "REFERENCES", "text", PAY412) in edges  # "Fixes PAY-412"
    assert (PR218, "REFERENCES", "text", slack_thread) in edges  # Slack permalink in PR body
    assert (slack_thread, "REFERENCES", "text", PAY412) in edges  # thread names the ticket
    comment = "jira:PAY:comment:30001"
    assert (comment, "REFERENCES", "text", PR218) in edges  # Jira comment links the PR URL
    assert (comment, "REFERENCES", "structural", PAY412) in edges
    assert any(t == "REPLIES_TO" and b == slack_thread for a, t, o, b in edges)

    records, _, _ = db.execute_query(
        "MATCH (a:Artifact) WHERE NOT coalesce(a.is_stub, false) RETURN a.provider AS p, collect(DISTINCT a.scope) AS s")
    scopes = {r["p"]: set(r["s"]) for r in records}
    assert scopes == {"github": {"acme-demo/shop"}, "jira": {"PAY", "SEC"}, "slack": {"C01PAY", "C02SUP", "C03ENG"}}

    sync._jobs.clear()  # a fresh process only has sync.json
    again = sync.sync_status(slug)
    assert again["state"] == "done" and again["complete"] and again["graph"] == graph and again["totals"] == first["totals"]

    sync.start_sync(slug, "deep")
    second = wait(slug)
    assert second["mode"] == "deep" and second["complete"] and second["graph"] == graph and _edges(db) == edges


def test_live_progress_and_409(home, db, monkeypatch):
    slug = demo_workspace()
    seen, release, calls = threading.Event(), threading.Event(), []
    original = Neo4jStore.write_artifact

    def slow(self, artifact):
        out = original(self, artifact)
        calls.append(1)
        if len(calls) == 3:
            seen.set()
            assert release.wait(30)
        return out

    monkeypatch.setattr(Neo4jStore, "write_artifact", slow)
    sync.start_sync(slug)
    assert seen.wait(30)
    mid = sync.sync_status(slug)
    assert mid["state"] == "running" and not mid["complete"] and "finished_at" not in mid
    assert mid["streams"][0]["status"] == "running" and mid["streams"][0]["pages"] == 1
    assert mid["totals"]["persisted"] == 2 and mid["totals"]["fetched"] >= 3
    with pytest.raises(RuntimeError, match="already running"):
        sync.start_sync(slug)
    assert json.loads((config.workspace_dir(slug) / "sync.json").read_text())["state"] == "running"
    release.set()
    assert wait(slug)["complete"]


def test_missing_credentials_fail_streams_safely(home, db):
    slug = config.create_workspace("Real")
    config.save_workspace(slug, {"name": "Real", "github": {"owner": "acme", "repos": ["api"]},
                                 "jira": {"site": "https://x.atlassian.net", "projects": ["PAY"]},
                                 "slack": {"workspace": "x", "channels": ["C1"]}})
    config.set_secrets(slug, {"jira_token": "SECRET-jira-token-value"})  # email missing
    sync.start_sync(slug)
    status = wait(slug)
    assert status["state"] == "failed" and not status["complete"]
    by = {s["stream"]: s for s in status["streams"]}
    assert set(by) == {"github:acme/api", "jira:PAY", "slack:C1"} and all(s["status"] == "failed" for s in by.values())
    assert by["github:acme/api"]["errors"][0]["message"] == "GitHub token not saved"
    assert by["jira:PAY"]["errors"][0]["message"] == "Jira email not saved"
    assert by["slack:C1"]["errors"][0]["message"] == "Slack token not saved"
    persisted = (config.workspace_dir(slug) / "sync.json").read_text()
    assert "SECRET-jira-token-value" not in json.dumps(status) + persisted


def test_api_sync_endpoints(home, monkeypatch):
    from hackfront.api import app

    http = TestClient(app)
    assert http.get("/api/w/nope/sync").status_code == 404
    assert http.post("/api/w/nope/sync").status_code == 404
    empty = config.create_workspace("Empty")
    assert http.get(f"/api/w/{empty}/sync").json()["state"] == "idle"
    for key in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"):
        monkeypatch.setenv(key, "x")
    assert http.post(f"/api/w/{empty}/sync").status_code == 422
    assert http.post(f"/api/w/{empty}/sync", json={"mode": "huge"}).status_code == 422
    slug = demo_workspace()
    monkeypatch.delenv("NEO4J_URI")
    assert http.post(f"/api/w/{slug}/sync").status_code == 503


def test_api_sync_runs_and_conflicts(home, db, monkeypatch):
    from hackfront.api import app

    http = TestClient(app)
    slug = demo_workspace()
    release, entered, original = threading.Event(), threading.Event(), Neo4jStore.write_artifact

    def slow(self, artifact):
        entered.set()
        assert release.wait(30)
        return original(self, artifact)

    monkeypatch.setattr(Neo4jStore, "write_artifact", slow)
    first = http.post(f"/api/w/{slug}/sync", json={"mode": "standard"})
    assert first.status_code == 202 and first.json()["state"] == "running"
    assert entered.wait(30)
    assert http.post(f"/api/w/{slug}/sync").status_code == 409
    assert http.get(f"/api/w/{slug}/sync").json()["state"] == "running"
    release.set()
    assert wait(slug)["complete"] and http.get(f"/api/w/{slug}/sync").json()["graph"]["artifacts"] > 0
