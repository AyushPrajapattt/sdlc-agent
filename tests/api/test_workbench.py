import json

import pytest
from fastapi.testclient import TestClient

from hackfront import config
from hackfront.api import app, workbench
from hackfront.ingest.demo import data as d
from tests.agent.unit.conftest import graph  # noqa: F401  (fixture)

client = TestClient(app)
REPO = f"{d.OWNER}/{d.REPO}"
WS = "alpha"
BASE = f"/api/w/{WS}/repo/{REPO}"
GW = "src/payments/gateway_client.py"


def cid(c):
    return f"github:acme-demo%2Fshop:commit:{c['sha']}"


class FakeDriver:
    """Answers the workbench commit query from the demo commits (only for the scope they belong to); records closes."""

    def __init__(self, commits=d.COMMITS):
        self.commits, self.closed, self.queries = commits, False, []

    def execute_query(self, query, **params):
        self.queries.append((query, params))
        rows = [{"id": cid(c), "time": c["commit"]["author"]["date"],
                 "paths": [f["filename"] for f in c["files"]], "raw": json.dumps(c)}
                for c in self.commits if params["ws"] == REPO]
        return rows, None, None

    def close(self):
        self.closed = True


class Keep:
    """Driver proxy: the throwaway test driver is session-scoped, so close() must not close it."""

    def __init__(self, driver):
        self.driver = driver

    def __getattr__(self, name):
        return getattr(self.driver, name)

    def close(self):
        pass


@pytest.fixture(autouse=True)
def workspaces(tmp_path, monkeypatch):
    """alpha connects the demo repo; beta connects something else."""
    monkeypatch.setattr(config, "HOME", tmp_path)
    for slug, repos in (("alpha", [REPO]), ("beta", ["other/thing"])):
        config.create_workspace(slug, slug=slug)
        config.save_workspace(slug, {"name": slug, "github": {"owner": "", "repos": repos}})


@pytest.fixture
def driver(monkeypatch):
    fake = FakeDriver()
    monkeypatch.setattr(config, "neo4j_driver", lambda: fake)
    return fake


def test_files_lists_touched_paths_and_closes_driver(driver):
    r = client.get(f"{BASE}/files")
    assert r.status_code == 200
    assert r.json()["files"] == sorted(d.FINAL_FILES)
    assert driver.closed and driver.queries[0][1]["ws"] == REPO  # commits are selected by scope == owner/repo


def test_file_blame_shape_and_key_line(driver):
    r = client.get(f"{BASE}/file", params={"path": GW})
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
    r = client.get(f"{BASE}/file", params={"path": path})
    assert r.status_code == 422 and "detail" in r.json()


@pytest.mark.parametrize("owner,repo", [("a b", "r"), ("o", "r$"), ("..", "r"), ("o", "..")])
def test_bad_repo_names_rejected(driver, owner, repo):
    assert client.get(f"/api/w/{WS}/repo/{owner}/{repo}/files").status_code in (404, 422)
    assert client.get(f"/api/w/{WS}/repo/{owner}/{repo}/file", params={"path": "a.py"}).status_code in (404, 422)


def test_unconnected_repo_and_unknown_file_are_404(driver):
    assert client.get(f"/api/w/{WS}/repo/nobody/nothing/files").status_code == 404
    assert client.get(f"/api/w/{WS}/repo/nobody/nothing/file", params={"path": "a.py"}).status_code == 404
    assert client.get(f"{BASE}/file", params={"path": "nope.py"}).status_code == 404


def test_repo_of_another_workspace_is_404_and_never_queried(driver):
    assert client.get(f"/api/w/beta/repo/{REPO}/files").status_code == 404  # ingested, but not beta's
    assert client.get(f"/api/w/beta/repo/{REPO}/file", params={"path": GW}).status_code == 404
    assert driver.queries == []


@pytest.mark.parametrize("ws", ["nope", "BAD SLUG", ".."])
def test_unknown_workspace_is_404(driver, ws):
    assert client.get(f"/api/w/{ws}/graph").status_code == 404
    assert client.get(f"/api/w/{ws}/repo/{REPO}/files").status_code == 404
    assert driver.queries == []


def test_missing_patch_marks_file_incomplete(monkeypatch):
    commits = json.loads(json.dumps(d.COMMITS))
    for c in commits:
        for f in c["files"]:
            if c["sha"] == d.C_RETRY["sha"]:
                f.pop("patch")
    monkeypatch.setattr(config, "neo4j_driver", lambda: FakeDriver(commits))
    body = client.get(f"{BASE}/file", params={"path": GW}).json()
    assert body["complete"] is False and body["lines"] == [] and "no patch" in body["note"]


def test_neo4j_down_is_503_without_leaking(monkeypatch):
    def boom():
        raise RuntimeError("bolt://user:SECRET@host")

    monkeypatch.setattr(config, "neo4j_driver", boom)
    r = client.get(f"{BASE}/files")
    assert r.status_code == 503 and "SECRET" not in r.text


def test_query_failure_is_500_safe(monkeypatch):
    class Bad(FakeDriver):
        def execute_query(self, *a, **k):
            raise RuntimeError("SECRET")

    fake = Bad()
    monkeypatch.setattr(config, "neo4j_driver", lambda: fake)
    r = client.get(f"/api/w/{WS}/graph")
    assert r.status_code == 500 and "SECRET" not in r.text and fake.closed


def test_graph_delegates_to_mapping_with_workspace_scopes_and_names(driver, monkeypatch):
    seen = []
    monkeypatch.setattr(workbench.mapping, "whole_graph",
                        lambda drv, scopes, names: seen.append((scopes, names)) or {"nodes": [], "edges": ["x"]})
    assert client.get(f"/api/w/{WS}/graph").json() == {"nodes": [], "edges": ["x"]}
    assert seen == [([REPO], {"channels": {}, "users": {}})]


# ---- real Neo4j (the throwaway test instance; skipped when unreachable)
def test_real_graph_is_limited_to_the_workspace_scopes(graph, monkeypatch):  # noqa: F811
    graph.execute_query("MATCH (a:Artifact) WHERE a.scope = 'acme' SET a.scope = $s", s=REPO)  # fixture graph: all 'acme'
    monkeypatch.setattr(config, "neo4j_driver", lambda: Keep(graph))
    mine = client.get(f"/api/w/{WS}/graph").json()
    assert len(mine["nodes"]) == 7 and mine["edges"]  # the seven non-stub artifacts
    assert client.get("/api/w/beta/graph").json() == {"nodes": [], "edges": []}
