"""The workbench overview against a REAL Neo4j (fake drivers hid a bad access-mode value once)."""

import time

from fastapi.testclient import TestClient

from hackfront import config
from hackfront.api.app import app
from hackfront.ingest.demo import DEMO_WORKSPACE
from hackfront.ingest.sync import start_sync, sync_status

client = TestClient(app)


def test_workbench_reports_neo4j_ok_and_indexed_repo_after_a_real_sync(clean_graph, tmp_path, monkeypatch):
    from tests.conftest import TEST_AUTH, TEST_URI

    monkeypatch.setattr(config, "HOME", tmp_path)
    for k, v in (("NEO4J_URI", TEST_URI), ("NEO4J_USERNAME", TEST_AUTH[0]), ("NEO4J_PASSWORD", TEST_AUTH[1])):
        monkeypatch.setenv(k, v)
    slug = config.create_workspace("Acme Demo", demo=True, slug="demo")
    config.save_workspace(slug, DEMO_WORKSPACE)
    start_sync(slug)
    for _ in range(240):
        if sync_status(slug)["state"] != "running":
            break
        time.sleep(0.25)
    body = client.get(f"/api/w/{slug}/workbench").json()
    assert body["neo4j"]["ok"] is True and body["neo4j"]["counts"]["artifacts"] > 0
    assert body["indexed_repos"] == ["acme-demo/shop"]
    assert body["workspace"]["targets"]["github"]["owner"] == "acme-demo"
