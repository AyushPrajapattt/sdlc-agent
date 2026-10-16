import pytest
from fastapi.testclient import TestClient

from hackfront import config
from hackfront.api import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)


def test_ui_origin_allowed_and_web_source_not_served():
    assert client.get("/web/app/page.tsx").status_code == 404  # the Next.js source tree must never be exposed
    bad = {"name": "  "}  # rejected by validation: no side effects
    assert client.post("/api/workspaces", json=bad, headers={"Origin": "http://localhost:3000"}).status_code == 422
    assert client.post("/api/workspaces", json=bad, headers={"Origin": "https://evil.example"}).status_code == 403


def test_cross_origin_mutation_refused_same_origin_allowed():
    assert client.post("/api/workspaces", json={"name": "a"}, headers={"Origin": "https://evil.example"}).status_code == 403
    assert client.get("/api/workspaces").json() == []  # nothing was created
    assert client.post("/api/workspaces", json={"name": "a"}, headers={"Origin": "http://testserver"}).status_code == 201


def test_jira_site_must_be_atlassian_cloud():
    for site in ("https://evil.example", "http://x.atlassian.net", "https://atlassian.net.evil.example"):
        with pytest.raises(ValueError):
            config.validate_workspace({"jira": {"site": site, "projects": []}})
    assert config.validate_workspace({"jira": {"site": "https://acme.atlassian.net", "projects": ["PAY"]}})


def test_access_token_guards_every_api_route_but_not_health(monkeypatch):
    assert client.get("/api/workspaces").status_code == 200  # no token configured: open (local dev)
    monkeypatch.setenv("HACKFRONT_ACCESS_TOKEN", "s3cret-token")
    assert client.get("/health").json() == {"ok": True}
    for headers in ({}, {"Authorization": "Bearer wrong"}, {"Authorization": "s3cret-token"}, {"Authorization": "bearer s3cret-token"}):
        assert client.get("/api/workspaces", headers=headers).status_code == 401, headers
    assert client.post("/api/workspaces", json={"name": "a"}).status_code == 401
    ok = {"Authorization": "Bearer s3cret-token"}
    assert client.get("/api/workspaces", headers=ok).status_code == 200
    assert client.post("/api/workspaces", json={"name": "a"}, headers=ok).status_code == 201
    assert "s3cret-token" not in client.get("/api/workspaces", headers=ok).text


def test_ui_on_any_localhost_port_is_trusted_but_lookalikes_are_not():
    bad = {"name": "  "}  # rejected by validation (422) after the origin check: no side effects
    for ok in ("http://localhost:3001", "http://127.0.0.1:4173", "http://localhost:3100", "http://[::1]:3000"):
        assert client.post("/api/workspaces", json=bad, headers={"Origin": ok}).status_code == 422, ok
    for evil in ("http://localhost.evil.com", "http://evil.com:3000", "https://127.0.0.1.evil.example", "null"):
        assert client.post("/api/workspaces", json=bad, headers={"Origin": evil}).status_code == 403, evil
