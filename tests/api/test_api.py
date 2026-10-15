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
