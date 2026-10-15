import pytest
from fastapi.testclient import TestClient

from hackfront import config
from hackfront.agent import llm
from hackfront.api import app, workspaces
from hackfront.ingest.sources.github.client import GitHubAPIError
from hackfront.ingest.sources.slack.client import SlackAPIError

client = TestClient(app)
SECRET = "ZZtopsecret-9f8e7d6c5b4a"


@pytest.fixture(autouse=True)
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    monkeypatch.setattr(llm, "_clients", {})
    monkeypatch.setattr(llm, "_creds", {})
    for env, _ in config.SECRETS.values():
        monkeypatch.delenv(env, raising=False)
    monkeypatch.setattr(config, "neo4j_driver", lambda: (_ for _ in ()).throw(RuntimeError(f"bolt://u:{SECRET}@h")))


def make(name="Acme", demo=False):
    r = client.post("/api/workspaces", json={"name": name, "demo": demo})
    assert r.status_code == 201, r.text
    return r.json()["slug"]


def test_create_list_delete_and_slug_rules():
    r = client.post("/api/workspaces", json={"name": "Acme Corp!"})
    assert r.json() == {"slug": "acme-corp", "name": "Acme Corp!", "demo": False}
    assert make("Acme Corp")  # slug is deduplicated, not an error
    rows = client.get("/api/workspaces").json()
    assert [x["slug"] for x in rows] == ["acme-corp", "acme-corp-2"]
    assert rows[0]["connected"] == {"repos": 0, "jira": 0, "slack": 0} and "last_sync" not in rows[0]
    assert client.post("/api/workspaces", json={"name": "   "}).status_code == 422
    assert client.post("/api/workspaces", json={}).status_code == 422
    assert client.delete("/api/workspaces/acme-corp").json() == {"ok": True}
    assert client.delete("/api/workspaces/acme-corp").status_code == 404
    assert client.delete("/api/workspaces/..%2Fx").status_code == 404
    assert client.get("/api/w/Bad_Slug/workbench").status_code == 404


def test_demo_creation_fills_targets():
    slug = make("Demo", demo=True)
    row = client.get("/api/workspaces").json()[0]
    assert row["demo"] is True and row["connected"]["repos"] >= 1 and row["connected"]["jira"] >= 1
    assert config.load_workspace(slug)["name"] == "Demo"


class FakeDriver:
    def __init__(self, fail_indexed=False):
        self.fail_indexed, self.queries = fail_indexed, []

    def session(self, **kw):
        assert kw["default_access_mode"] == "READ"  # neo4j.READ_ACCESS; a lowercase "r" is rejected by the real driver
        return self

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass

    def run(self, query, **params):
        self.queries.append((query, params))
        if "DISTINCT a.scope" in query:
            if self.fail_indexed:
                raise RuntimeError("boom")
            rows = [{"scope": "acme/api"}]
        elif "count(a)" in query:
            rows = [{"artifacts": 7}]
        else:
            rows = [{"edges": 5, "stubs": 2}]
        return type("R", (), {"data": lambda self: rows})()


def walk(value):
    if isinstance(value, dict):
        for k, v in value.items():
            yield k
            yield from walk(v)
    elif isinstance(value, list):
        for v in value:
            yield from walk(v)
    else:
        yield value


def test_workbench_shape_and_secrets_never_leak(monkeypatch):
    slug = make()
    driver = FakeDriver()
    monkeypatch.setattr(config, "neo4j_driver", lambda: driver)
    monkeypatch.setenv("GITHUB_TOKEN", SECRET)
    r = client.put(f"/api/w/{slug}/workspace", json={"github": {"owner": "acme", "repos": ["api", "web"]}})
    assert r.status_code == 200
    s = client.put(f"/api/w/{slug}/secrets", json={"slack_token": SECRET + "slack", "jira_email": "me@x.io",
                                                   "sarvam_key": SECRET + "sarvam"})
    assert s.status_code == 200 and SECRET not in s.text
    r = client.get(f"/api/w/{slug}/workbench")
    assert r.status_code == 200 and SECRET not in r.text
    body = r.json()
    assert {k: body["workspace"][k] for k in ("slug", "name", "demo")} == {"slug": slug, "name": "Acme", "demo": False}
    assert set(body["workspace"]["targets"]) == {"github", "jira", "slack"}  # non-secret targets only
    assert body["connected"] == body["catalog"] == {"repos": ["acme/api", "acme/web"], "jira": [], "slack": []}
    assert body["indexed_repos"] == ["acme/api"]
    assert body["neo4j"] == {"ok": True, "counts": {"artifacts": 7, "edges": 5, "stubs": 2}}
    assert driver.queries[0][1] == {"repos": ["acme/api", "acme/web"]}
    gh, jira, slack, llm_ = (body["integrations"][k] for k in ("github", "jira", "slack", "llm"))
    assert gh["configured"] is True and gh["targets"] == 2 and list(gh["secrets"]) == ["github_token"]
    assert gh["secrets"]["github_token"]["source"] == "env" and gh["secrets"]["github_token"]["hint"].startswith("••••")
    assert jira["configured"] is False and jira["secrets"]["jira_email"]["value"] == "me@x.io"
    assert slack["configured"] is False and slack["secrets"]["slack_token"]["source"] == "workspace"  # no channels yet
    assert llm_["configured"] is True and "targets" not in llm_
    assert {p["name"]: p["configured"] for p in body["providers"]} == {"azure": False, "sarvam": True}
    assert body["names"] == {"channels": {}, "users": {}}


def test_workbench_neo4j_errors_are_swallowed(monkeypatch):
    slug = make()
    r = client.get(f"/api/w/{slug}/workbench")  # driver raises with a secret-looking message
    assert r.status_code == 200 and SECRET not in r.text
    assert r.json()["neo4j"] == {"ok": False} and r.json()["indexed_repos"] == []
    monkeypatch.setattr(config, "neo4j_driver", lambda: FakeDriver(fail_indexed=True))
    body = client.get(f"/api/w/{slug}/workbench").json()
    assert body["neo4j"]["ok"] is True and body["indexed_repos"] == []


def test_workbench_demo_is_configured():
    slug = make(demo=True)
    integ = client.get(f"/api/w/{slug}/workbench").json()["integrations"]
    assert [integ[k]["configured"] for k in ("github", "jira", "slack", "llm")] == [True, True, True, False]


def test_put_workspace_merges_and_validates():
    slug = make()
    config.save_workspace(slug, {**config.load_workspace(slug), "slack": {
        "workspace": "w", "channels": ["C1"], "channel_names": {"C1": "dev"}, "users": {"U1": "Ann"}}, "demo": True})
    r = client.put(f"/api/w/{slug}/workspace", json={
        "name": "Renamed", "github": {"owner": "o"},
        "slack": {"channels": ["C1", "C2"], "channel_names": {"C9": "evil"}, "users": {}}, "demo": False})
    assert r.status_code == 200
    out = r.json()
    assert out["name"] == "Renamed" and out["demo"] is True and out["github"] == {"owner": "o", "repos": []}
    assert out["slack"] == {"workspace": "w", "channels": ["C1", "C2"], "channel_names": {"C1": "dev"}, "users": {"U1": "Ann"}}
    assert config.load_workspace(slug) == out
    bad = client.put(f"/api/w/{slug}/workspace", json={"jira": {"site": "http://x"}})
    assert bad.status_code == 422 and "https" in bad.json()["detail"]
    assert client.put(f"/api/w/{slug}/workspace", json={"github": {"repos": "r"}}).status_code == 422
    assert client.put(f"/api/w/{slug}/workspace", json={"github": []}).status_code == 422
    assert client.put("/api/w/nope/workspace", json={}).status_code == 404
    assert config.load_workspace(slug) == out  # failures change nothing


def test_secrets_partial_update_and_clear():
    slug = make()
    r = client.put(f"/api/w/{slug}/secrets", json={"github_token": SECRET, "jira_email": "a@b.c"})
    assert SECRET not in r.text
    st = r.json()
    assert st["github_token"]["set"] and "value" not in st["github_token"] and st["jira_email"]["value"] == "a@b.c"
    client.put(f"/api/w/{slug}/secrets", json={"slack_token": "xoxb-1234567890123"})
    st = client.put(f"/api/w/{slug}/secrets", json={"github_token": ""}).json()
    assert st["github_token"] == {"set": False, "source": None}
    assert st["slack_token"]["set"] and st["jira_email"]["set"]  # untouched keys stay
    bad = client.put(f"/api/w/{slug}/secrets", json={"nope": SECRET})
    assert bad.status_code == 422 and SECRET not in bad.text
    assert client.put(f"/api/w/{slug}/secrets", json={"github_token": "a\nb"}).status_code == 422
    assert client.put("/api/w/nope/secrets", json={}).status_code == 404


class FakeGitHub:
    error = None

    def __init__(self, token=None):
        self.token = token

    def whoami(self):
        if self.error:
            raise self.error
        return "octocat"

    def list_repos(self, owner):
        if self.error:
            raise self.error
        return [{"full_name": f"{owner or 'me'}/api", "private": True}]


def test_integration_tests_ok_and_safe_failures(monkeypatch):
    slug = make()
    monkeypatch.setattr(workspaces, "GitHubClient", FakeGitHub)
    url = f"/api/w/{slug}/integrations/github/test"
    assert client.post(url).json() == {"ok": False, "detail": "GitHub token not saved"}
    client.put(f"/api/w/{slug}/secrets", json={"github_token": SECRET})
    assert client.post(url).json() == {"ok": True, "detail": "Connected", "account": "octocat"}
    for error, detail in [(GitHubAPIError("x", 401), "GitHub rejected the credentials (HTTP 401)"),
                          (GitHubAPIError("https://h/?t=" + SECRET), "Network error"),
                          (GitHubAPIError(SECRET, 500), "GitHub returned HTTP 500"),
                          (RuntimeError(SECRET), "Network error")]:
        FakeGitHub.error = error
        r = client.post(url)
        assert r.status_code == 200 and r.json() == {"ok": False, "detail": detail} and SECRET not in r.text
    FakeGitHub.error = None
    assert client.post(f"/api/w/{slug}/integrations/nope/test").status_code == 422
    assert client.post("/api/w/nope/integrations/github/test").status_code == 404


def test_jira_slack_tests_with_fakes(monkeypatch):
    slug = make()
    jira = type("J", (), {"__init__": lambda s, site, token, email=None: None,
                          "myself": lambda s: {"displayName": "Ann", "emailAddress": "ann@x.io"}})
    slack = type("S", (), {"__init__": lambda s, token: None,
                           "auth_test": lambda s: (_ for _ in ()).throw(SlackAPIError("Slack API error: invalid_auth", 200))})
    monkeypatch.setattr(workspaces, "JiraClient", jira)
    monkeypatch.setattr(workspaces, "SlackClient", slack)
    assert client.post(f"/api/w/{slug}/integrations/jira/test").json()["detail"] == "Jira email and token not saved"
    client.put(f"/api/w/{slug}/secrets", json={"jira_email": "a@b.c", "jira_token": SECRET, "slack_token": SECRET})
    assert client.post(f"/api/w/{slug}/integrations/jira/test").json()["detail"] == "Jira site not set"
    client.put(f"/api/w/{slug}/workspace", json={"jira": {"site": "https://a.atlassian.net"}})
    assert client.post(f"/api/w/{slug}/integrations/jira/test").json() == {"ok": True, "detail": "Connected", "account": "ann@x.io"}
    assert client.post(f"/api/w/{slug}/integrations/slack/test").json() == {
        "ok": False, "detail": "Slack API error: invalid_auth"}


def test_demo_integration_tests_and_resources():
    slug = make(demo=True)
    for which in ("github", "jira", "slack"):
        r = client.post(f"/api/w/{slug}/integrations/{which}/test").json()
        assert r["ok"] is True and r["detail"] == "Demo data", (which, r)
        res = client.get(f"/api/w/{slug}/integrations/{which}/resources")
        assert res.status_code == 200 and res.json()["resources"], which
    chans = client.get(f"/api/w/{slug}/integrations/slack/resources").json()["resources"]
    assert chans[0]["name"].startswith("#") and chans[0]["detail"] in ("bot is a member", "bot not invited")


def test_resources_with_fakes_and_failures(monkeypatch):
    slug = make()
    for which, msg in (("github", "GitHub token not saved"), ("jira", "Jira email and token not saved"),
                       ("slack", "Slack token not saved")):
        r = client.get(f"/api/w/{slug}/integrations/{which}/resources")
        assert r.status_code == 422 and r.json()["detail"] == msg
    monkeypatch.setattr(workspaces, "GitHubClient", FakeGitHub)
    client.put(f"/api/w/{slug}/secrets", json={"github_token": SECRET})
    client.put(f"/api/w/{slug}/workspace", json={"github": {"owner": "acme"}})
    assert client.get(f"/api/w/{slug}/integrations/github/resources").json() == {
        "resources": [{"id": "acme/api", "name": "acme/api", "private": True}]}
    FakeGitHub.error = GitHubAPIError(SECRET, 401)
    r = client.get(f"/api/w/{slug}/integrations/github/resources")
    FakeGitHub.error = None
    assert r.status_code == 502 and SECRET not in r.text and "HTTP 401" in r.json()["detail"]

    slack = type("S", (), {"__init__": lambda s, token: None, "channels": lambda s: [
        {"id": "C1", "name": "dev", "is_private": False, "is_member": True},
        {"id": "C2", "name": "ops", "is_private": True, "is_member": False}]})
    monkeypatch.setattr(workspaces, "SlackClient", slack)
    client.put(f"/api/w/{slug}/secrets", json={"slack_token": SECRET})
    assert client.get(f"/api/w/{slug}/integrations/slack/resources").json()["resources"] == [
        {"id": "C1", "name": "#dev", "private": False, "detail": "bot is a member"},
        {"id": "C2", "name": "#ops", "private": True, "detail": "bot not invited"}]


def test_llm_test_uses_workspace_credentials(monkeypatch):
    slug = make()
    url = f"/api/w/{slug}/integrations/llm/test"
    assert client.post(url).json() == {"ok": False, "detail": "No LLM key saved"}
    seen = []
    monkeypatch.setattr(llm, "ping", lambda provider: seen.append((provider, llm._key(provider))) or "ok")
    client.put(f"/api/w/{slug}/secrets", json={"sarvam_key": SECRET})
    r = client.post(url)
    assert r.json() == {"ok": True, "detail": "Model replied", "account": "sarvam (sarvam-105b)"}
    assert seen == [("sarvam", SECRET)] and SECRET not in r.text
    monkeypatch.setattr(llm, "ping", lambda provider: (_ for _ in ()).throw(RuntimeError("sarvam rejected the request (HTTP 401)")))
    assert client.post(url).json() == {"ok": False, "detail": "sarvam rejected the request (HTTP 401)"}
    client.put(f"/api/w/{slug}/secrets", json={"llm_provider": "bogus"})
    assert client.post(url).json() == {"ok": False, "detail": "Unknown LLM provider"}
    assert llm._workspace.get() is None


def test_llm_per_workspace_credentials_and_client_cache(monkeypatch):
    slug = make()
    monkeypatch.setenv("SARVAM_API_KEY", "env-key-1")
    config.set_secrets(slug, {"sarvam_key": "ws-key-2", "llm_model": "sarvam-30b", "llm_provider": "sarvam"})
    assert llm.providers() == [{"name": "azure", "model": "Kimi-K2.5", "configured": False},
                               {"name": "sarvam", "model": "sarvam-105b", "configured": True}]
    assert llm.providers(slug)[1] == {"name": "sarvam", "model": "sarvam-30b", "configured": True}
    assert llm._workspace.get() is None
    first = llm.client("sarvam")  # env only
    llm.set_workspace(slug)
    try:
        second = llm.client("sarvam")
        assert second is not first and second.api_key == "ws-key-2" and llm.client("sarvam") is second
        config.set_secrets(slug, {"sarvam_key": "ws-key-3"})
        assert llm.client("sarvam").api_key == "ws-key-3"  # a changed key never reuses the old client
    finally:
        llm.set_workspace(None)


def test_llm_ping_is_sanitized(monkeypatch):
    class Boom(Exception):
        status_code = 401

    def fake(exc):
        def create(**kw):
            raise exc

        return type("C", (), {"chat": type("X", (), {"completions": type("Y", (), {"create": staticmethod(create)})})})

    monkeypatch.setattr(llm, "_clients", {"sarvam": fake(Boom(SECRET))})
    with pytest.raises(RuntimeError) as e:
        llm.ping("sarvam")
    assert str(e.value) == "sarvam rejected the request (HTTP 401)" and SECRET not in str(e.value)
    monkeypatch.setattr(llm, "_clients", {"sarvam": fake(OSError(SECRET))})
    with pytest.raises(RuntimeError, match="could not reach sarvam"):
        llm.ping("sarvam")
