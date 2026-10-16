"""Workspace state behaves identically on the file backend and the Neo4j backend (HACKFRONT_STATE=neo4j)."""

import pytest
from fastapi.testclient import TestClient

from hackfront import config, state
from hackfront.agent import investigation as inv_store
from hackfront.api import app

TOKEN = "ghp_SUPERSECRETTOKENVALUE1234567890"


@pytest.fixture(params=["file", "neo4j"])
def kind(request, tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setenv("HACKFRONT_STATE", request.param)
    for key in ("GITHUB_TOKEN", "SLACK_BOT_TOKEN", "AZURE_FOUNDRY_API_KEY", "SARVAM_API_KEY"):
        monkeypatch.delenv(key, raising=False)
    if request.param == "neo4j":
        from tests.conftest import TEST_AUTH, TEST_URI

        driver = request.getfixturevalue("neo4j_test_driver")
        monkeypatch.setenv("NEO4J_URI", TEST_URI)
        monkeypatch.setenv("NEO4J_USERNAME", TEST_AUTH[0])
        monkeypatch.setenv("NEO4J_PASSWORD", TEST_AUTH[1])
        monkeypatch.setenv("HACKFRONT_SECRET_KEY", "test-secret-key")
        driver.execute_query("MATCH (n) DETACH DELETE n")
        state.reset_caches()
        monkeypatch.setattr(state, "CACHE_SECONDS", 0)  # no stale reads between steps of one test
    return request.param


def investigation(iid, created, question="Why?"):
    return {"investigation": {"id": iid, "question": question, "file": "a.py", "line": 3, "confidence": "high",
                              "created_at": created, "claims": []}, "graph": {"nodes": [], "edges": []}}


def test_workspace_lifecycle(kind):
    a = config.create_workspace("Acme Team")
    assert a == "acme-team" and config.create_workspace("Acme Team") == "acme-team-2"
    with pytest.raises(ValueError):
        config.create_workspace("x", slug="acme-team")
    assert {w["slug"] for w in config.list_workspaces()} == {"acme-team", "acme-team-2"}
    config.save_workspace(a, {**config.load_workspace(a), "github": {"owner": "acme", "repos": ["api"]},
                              "slack": {"workspace": "acme", "channels": ["C1"], "channel_names": {"C1": "eng"}, "users": {"U1": "dana"}}})
    assert config.scopes(a)["repos"] == ["acme/api"] and config.names(a) == {"channels": {"C1": "eng"}, "users": {"U1": "dana"}}
    config.delete_workspace(a)
    with pytest.raises(LookupError):
        config.load_workspace(a)
    with pytest.raises(LookupError):
        config.delete_workspace(a)
    assert [w["slug"] for w in config.list_workspaces()] == ["acme-team-2"]


def test_secrets_roundtrip_mask_clear_and_isolation(kind):
    a, b = config.create_workspace("A"), config.create_workspace("B")
    config.set_secrets(a, {"github_token": TOKEN, "jira_email": "dana@acme.com"})
    assert config.get_secret(a, "github_token") == TOKEN and config.get_secret(b, "github_token") is None
    status = config.secret_status(a)
    assert status["github_token"] == {"set": True, "source": "workspace", "hint": "••••7890"}
    assert status["jira_email"]["value"] == "dana@acme.com" and TOKEN not in repr(status)
    config.set_secrets(a, {"github_token": ""})  # clear
    assert config.get_secret(a, "github_token") is None and config.get_secret(a, "jira_email") == "dana@acme.com"
    with pytest.raises(ValueError):
        config.set_secrets(a, {"nope": "x"})
    with pytest.raises(LookupError):
        config.set_secrets("ghost", {"github_token": TOKEN})


def test_investigations_and_sync_status_per_workspace(kind):
    a, b = config.create_workspace("A"), config.create_workspace("B")
    inv_store.save(investigation("older", "2026-10-01T10:00:00Z", "first")["investigation"], {"nodes": [], "edges": []}, a)
    inv_store.save(investigation("newer", "2026-10-02T10:00:00Z", "second")["investigation"], {"nodes": [], "edges": []}, a)
    assert [r["id"] for r in inv_store.list_all(a)] == ["newer", "older"]
    assert inv_store.list_all(a)[0] == {"id": "newer", "question": "second", "file": "a.py", "line": 3,
                                        "confidence": "high", "created_at": "2026-10-02T10:00:00Z"}
    assert inv_store.get("newer", a)["investigation"]["question"] == "second"
    assert inv_store.get("newer", b) is None and inv_store.list_all(b) == []  # isolation
    assert inv_store.get("../../etc/passwd", a) is None and inv_store.get("missing", a) is None

    be = state.backend()
    assert be.read_sync(a) is None
    be.write_sync(a, {"state": "done", "streams": [], "complete": True})
    assert be.read_sync(a)["state"] == "done" and be.read_sync(b) is None
    config.delete_workspace(a)
    assert inv_store.list_all(a) == [] and be.read_sync(a) is None
    with pytest.raises(FileNotFoundError):
        be.write_sync(a, {"state": "running"})  # a deleted workspace must not be resurrected by a late sync write


# ---------------------------------------------------------------- neo4j-specific guarantees
@pytest.fixture
def pg(neo4j_test_driver, tmp_path, monkeypatch):
    from tests.conftest import TEST_AUTH, TEST_URI

    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setenv("HACKFRONT_STATE", "neo4j")
    monkeypatch.setenv("NEO4J_URI", TEST_URI)
    monkeypatch.setenv("NEO4J_USERNAME", TEST_AUTH[0])
    monkeypatch.setenv("NEO4J_PASSWORD", TEST_AUTH[1])
    monkeypatch.setenv("HACKFRONT_SECRET_KEY", "test-secret-key")
    monkeypatch.delenv("GITHUB_TOKEN", raising=False)
    neo4j_test_driver.execute_query("MATCH (n) DETACH DELETE n")
    state.reset_caches()
    monkeypatch.setattr(state, "CACHE_SECONDS", 0)
    return neo4j_test_driver


def blob(driver, slug):
    return driver.execute_query("MATCH (s:HfSecret {slug: $s}) RETURN s.blob AS b", s=slug).records[0]["b"]


def test_keys_are_encrypted_at_rest_and_degrade_safely(pg, monkeypatch):
    slug = config.create_workspace("Crypto")
    config.set_secrets(slug, {"github_token": TOKEN})
    stored = blob(pg, slug)
    assert TOKEN not in stored and "ghp_" not in stored and stored.startswith("gAAAA")  # Fernet token
    assert config.get_secret(slug, "github_token") == TOKEN

    monkeypatch.setenv("HACKFRONT_SECRET_KEY", "a-different-key")  # wrong key: unreadable == unset, never garbage
    assert config.get_secret(slug, "github_token") is None and config.secret_status(slug)["github_token"]["set"] is False
    monkeypatch.setenv("GITHUB_TOKEN", "env-fallback-token")  # the environment fallback still works
    assert config.get_secret(slug, "github_token") == "env-fallback-token"

    monkeypatch.delenv("HACKFRONT_SECRET_KEY")  # no key configured: refuse to save, keep working read-only
    with pytest.raises(ValueError, match="HACKFRONT_SECRET_KEY"):
        config.set_secrets(slug, {"github_token": "another"})


def test_state_nodes_are_invisible_to_the_evidence_graph(pg):
    slug = config.create_workspace("Hidden")
    config.set_secrets(slug, {"github_token": TOKEN})
    inv_store.save(investigation("i1", "2026-10-02T10:00:00Z")["investigation"], {"nodes": [], "edges": []}, slug)
    assert pg.execute_query("MATCH (a:Artifact) RETURN count(a) AS n").records[0]["n"] == 0
    from hackfront.api import mapping

    assert mapping.whole_graph(pg, ["acme/api", "PAY", "C1"]) == {"nodes": [], "edges": []}


def test_state_survives_a_restart_and_reads_are_cached_copies(pg, monkeypatch):
    slug = config.create_workspace("Durable")
    config.set_secrets(slug, {"github_token": TOKEN})
    state.reset_caches()  # simulates a fresh process: nothing in memory
    assert config.load_workspace(slug)["name"] == "Durable" and config.get_secret(slug, "github_token") == TOKEN

    monkeypatch.setattr(state, "CACHE_SECONDS", 60)
    first = config.load_workspace(slug)
    first["name"] = "mutated by a caller"
    assert config.load_workspace(slug)["name"] == "Durable"  # the cache hands out copies
    config.save_workspace(slug, {**config.load_workspace(slug), "name": "Renamed"})
    assert config.load_workspace(slug)["name"] == "Renamed"  # a write in this process is visible immediately


def test_migrate_file_state_into_neo4j(pg, tmp_path, monkeypatch):
    monkeypatch.setenv("HACKFRONT_STATE", "file")
    slug = config.create_workspace("Local One")
    config.set_secrets(slug, {"github_token": TOKEN})
    inv_store.save(investigation("i1", "2026-10-02T10:00:00Z", "from disk")["investigation"], {"nodes": [], "edges": []}, slug)
    state.FileState().write_sync(slug, {"state": "done", "streams": [], "complete": True})

    result = state.migrate(state.FileState(), state.Neo4jState())
    assert result["workspaces"] == 1 and result["secrets"] == 1 and result["investigations"] == 1 and not result["skipped"]
    monkeypatch.setenv("HACKFRONT_STATE", "neo4j")
    assert config.load_workspace(slug)["name"] == "Local One" and config.get_secret(slug, "github_token") == TOKEN
    assert inv_store.get("i1", slug)["investigation"]["question"] == "from disk"
    assert state.Neo4jState().read_sync(slug)["state"] == "done"
    assert state.migrate(state.FileState(), state.Neo4jState())["skipped"] == [slug]  # never overwrites by default

    monkeypatch.delenv("HACKFRONT_SECRET_KEY")  # without a key, keys are skipped (and reported), the rest still moves
    pg.execute_query("MATCH (n) DETACH DELETE n")
    state.reset_caches()
    again = state.migrate(state.FileState(), state.Neo4jState())
    assert again["workspaces"] == 1 and again["secrets"] == 0 and again["secrets_skipped"] == [slug]


def test_api_end_to_end_on_neo4j_state(pg, monkeypatch):
    client = TestClient(app)
    slug = client.post("/api/workspaces", json={"name": "Hosted"}).json()["slug"]
    assert [w["slug"] for w in client.get("/api/workspaces").json()] == [slug]
    r = client.put(f"/api/w/{slug}/secrets", json={"github_token": TOKEN})
    assert r.status_code == 200 and r.json()["github_token"]["hint"] == "••••7890" and TOKEN not in r.text
    assert TOKEN not in client.get(f"/api/w/{slug}/workbench").text
    state.reset_caches()  # "restart"
    assert client.get(f"/api/w/{slug}/workbench").json()["integrations"]["github"]["secrets"]["github_token"]["set"] is True

    monkeypatch.delenv("HACKFRONT_SECRET_KEY")
    r = client.put(f"/api/w/{slug}/secrets", json={"github_token": "x"})
    assert r.status_code == 422 and "HACKFRONT_SECRET_KEY" in r.json()["detail"]
    assert client.delete(f"/api/workspaces/{slug}").status_code == 200 and client.get("/api/workspaces").json() == []
