import json
import sys
import types

import pytest
from fastapi.testclient import TestClient

from hackfront import config
from hackfront.api import app, workbench
from hackfront.ingest.demo import data as d

client = TestClient(app)
WS = f"{d.OWNER}/{d.REPO}"
GW = "src/payments/gateway_client.py"


def cid(c):
    return f"github:acme-demo%2Fshop:commit:{c['sha']}"


class FakeDriver:
    """Answers the workbench queries from the demo commits; records closes."""

    def __init__(self, commits=d.COMMITS, scopes=None):
        self.commits, self.closed = commits, False
        self.scopes = scopes or {}

    def execute_query(self, query, **params):
        if "git_commit" in query and "$ws" in query:
            rows = [{"id": cid(c), "time": c["commit"]["author"]["date"],
                     "paths": [f["filename"] for f in c["files"]], "raw": json.dumps(c)}
                    for c in self.commits if params["ws"] == WS]
        else:
            key = next(k for k in workbench._SCOPES if workbench._SCOPES[k] == query)
            rows = [{"v": v} for v in self.scopes.get(key, [])]
        return rows, None, None

    def close(self):
        self.closed = True


@pytest.fixture
def driver(monkeypatch):
    fake = FakeDriver()
    monkeypatch.setattr(config, "neo4j_driver", lambda: fake)
    return fake


def fake_module(monkeypatch, name, **attrs):
    mod = types.ModuleType(name)
    mod.__dict__.update(attrs)
    monkeypatch.setitem(sys.modules, name, mod)


def test_files_lists_touched_paths_and_closes_driver(driver):
    r = client.get(f"/api/repo/{WS}/files")
    assert r.status_code == 200
    assert r.json()["files"] == sorted(d.FINAL_FILES)
    assert driver.closed


def test_file_blame_shape_and_key_line(driver):
    r = client.get(f"/api/repo/{WS}/file", params={"path": GW})
    body = r.json()
    assert r.status_code == 200 and body["complete"] is True and body["path"] == GW
    assert [x["text"] for x in body["lines"]] == d.FINAL_FILES[GW].splitlines()
    line = next(x for x in body["lines"] if x["text"] == "MAX_RETRIES = 3")
    assert line["blame"] == cid(d.C_RETRY)


def test_same_timestamp_commits_follow_parent_order():
    rows = [{"id": cid(c), "time": "T", "raw": json.dumps(c)} for c in (d.C_RETRY, d.C_REFRESH)]  # child listed first
    assert [r["id"] for r in workbench._ordered(rows)] == [cid(d.C_REFRESH), cid(d.C_RETRY)]


@pytest.mark.parametrize("path", ["", "/etc/passwd", "../x", "a/../b", "a//b", "a\\b", "a\0b", "x" * 301, "./a"])
def test_bad_paths_rejected(driver, path):
    r = client.get(f"/api/repo/{WS}/file", params={"path": path})
    assert r.status_code == 422 and "detail" in r.json()


@pytest.mark.parametrize("owner,repo", [("a b", "r"), ("o", "r$"), ("..", "r"), ("o", "..")])
def test_bad_repo_names_rejected(driver, owner, repo):
    assert client.get(f"/api/repo/{owner}/{repo}/files").status_code in (404, 422)
    assert client.get(f"/api/repo/{owner}/{repo}/file", params={"path": "a.py"}).status_code in (404, 422)


def test_unindexed_repo_and_unknown_file_are_404(driver):
    assert client.get("/api/repo/nobody/nothing/files").status_code == 404
    assert client.get("/api/repo/nobody/nothing/file", params={"path": "a.py"}).status_code == 404
    assert client.get(f"/api/repo/{WS}/file", params={"path": "nope.py"}).status_code == 404


def test_missing_patch_marks_file_incomplete(monkeypatch):
    commits = json.loads(json.dumps(d.COMMITS))
    for c in commits:
        for f in c["files"]:
            if c["sha"] == d.C_RETRY["sha"]:
                f.pop("patch")
    monkeypatch.setattr(config, "neo4j_driver", lambda: FakeDriver(commits))
    body = client.get(f"/api/repo/{WS}/file", params={"path": GW}).json()
    assert body["complete"] is False and body["lines"] == [] and "no patch" in body["note"]


def test_neo4j_down_is_503_without_leaking(monkeypatch):
    def boom():
        raise RuntimeError("bolt://user:SECRET@host")

    monkeypatch.setattr(config, "neo4j_driver", boom)
    r = client.get(f"/api/repo/{WS}/files")
    assert r.status_code == 503 and "SECRET" not in r.text


def test_query_failure_is_500_safe(monkeypatch):
    class Bad(FakeDriver):
        def execute_query(self, *a, **k):
            raise RuntimeError("SECRET")

    fake = Bad()
    monkeypatch.setattr(config, "neo4j_driver", lambda: fake)
    r = client.get("/api/graph")
    assert r.status_code == 500 and "SECRET" not in r.text and fake.closed


def test_graph_delegates_to_mapping(driver, monkeypatch):
    monkeypatch.setattr(workbench.mapping, "whole_graph", lambda drv: {"nodes": [], "edges": ["x"]})
    assert client.get("/api/graph").json() == {"nodes": [], "edges": ["x"]}


def test_workbench_overview(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_FILE", tmp_path / "workspace.json")
    config.save_workspace({"github": {"owner": "acme", "repos": ["shop"]}, "jira": {"projects": ["PAY"]},
                           "slack": {"channels": ["C1"]}})
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_SECRET1")
    fake = FakeDriver(scopes={"repos": ["acme/shop", "other/x"], "jira": ["SEC"], "indexed": ["acme/shop"],
                              "slack": [json.dumps({"channel_id": "C2"}), "not json", json.dumps({})]})
    monkeypatch.setattr(config, "neo4j_driver", lambda: fake)
    fake_module(monkeypatch, "hackfront.ingest.sync", graph_counts=lambda: {"artifacts": 3})
    fake_module(monkeypatch, "hackfront.agent", providers=lambda: [{"name": "p", "model": "m", "configured": True}])
    r = client.get("/api/workbench")
    body = r.json()
    assert r.status_code == 200 and "SECRET" not in r.text
    assert body["workspace"] == {"slug": "local", "name": "acme"}
    assert body["connected"] == {"repos": ["acme/shop"], "jira": ["PAY"], "slack": ["C1"]}
    assert body["catalog"] == {"repos": ["acme/shop", "other/x"], "jira": ["PAY", "SEC"], "slack": ["C1", "C2"]}
    assert body["indexed_repos"] == ["acme/shop"]
    assert body["neo4j"] == {"ok": True, "counts": {"artifacts": 3}}
    assert body["sources"]["github"] == {"token_present": True}
    assert body["providers"][0]["name"] == "p" and fake.closed


def test_workbench_degrades_when_everything_is_down(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "WORKSPACE_FILE", tmp_path / "workspace.json")

    def boom(*a, **k):
        raise RuntimeError("down")

    monkeypatch.setattr(config, "neo4j_driver", boom)
    fake_module(monkeypatch, "hackfront.ingest.sync", graph_counts=boom)
    fake_module(monkeypatch, "hackfront.agent", providers=boom)
    body = client.get("/api/workbench").json()
    assert body["neo4j"] == {"ok": False} and body["providers"] == [] and body["indexed_repos"] == []
    assert body["workspace"] == {"slug": "local", "name": "Local"}
    assert body["catalog"] == {"repos": [], "jira": [], "slack": []}


# ---- real Neo4j (the throwaway test instance; skipped when unreachable)
def test_real_graph_file_endpoint(clean_graph, monkeypatch, tmp_path):
    from hackfront.ingest.demo import DEMO_WORKSPACE
    from hackfront.ingest.sync import sync_workspace
    from tests.conftest import TEST_AUTH, TEST_URI

    monkeypatch.setattr(config, "WORKSPACE_FILE", tmp_path / "workspace.json")
    monkeypatch.setenv("NEO4J_URI", TEST_URI)
    monkeypatch.setenv("NEO4J_USERNAME", TEST_AUTH[0])
    monkeypatch.setenv("NEO4J_PASSWORD", TEST_AUTH[1])
    assert all(s["complete"] for s in sync_workspace(DEMO_WORKSPACE, demo=True))

    body = client.get(f"/api/repo/{WS}/file", params={"path": GW}).json()
    assert body["complete"] is True
    assert [x["text"] for x in body["lines"]] == d.FINAL_FILES[GW].splitlines()
    assert next(x for x in body["lines"] if x["text"] == "MAX_RETRIES = 3")["blame"] == cid(d.C_RETRY)
    assert set(client.get(f"/api/repo/{WS}/files").json()["files"]) == set(d.FINAL_FILES)
    ids = {n["id"] for n in client.get("/api/graph").json()["nodes"]}
    assert cid(d.C_RETRY) in ids  # blame ids are real graph node ids
    wb = client.get("/api/workbench").json()
    assert WS in wb["indexed_repos"] and {"PAY", "SEC"} <= set(wb["catalog"]["jira"])
    assert {"C01PAY", "C02SUP", "C03ENG"} <= set(wb["catalog"]["slack"]) and wb["neo4j"]["ok"]
