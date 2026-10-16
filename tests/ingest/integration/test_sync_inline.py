"""Serverless-ready sync: in-request run with a time budget, heartbeat-guarded status shared across instances."""

import time
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from hackfront import config, state
from hackfront.api import app
from hackfront.ingest import sync
from hackfront.ingest.demo import DEMO_WORKSPACE


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "HOME", tmp_path)
    for key in ("HACKFRONT_STATE", "HACKFRONT_SYNC", "VERCEL", "HACKFRONT_SYNC_BUDGET"):
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


def iso(seconds_ago):
    return (datetime.now(timezone.utc) - timedelta(seconds=seconds_ago)).strftime("%Y-%m-%dT%H:%M:%SZ")


def persisted_running(slug, heartbeat):
    state.backend().write_sync(slug, {"state": "running", "mode": "standard", "heartbeat": heartbeat, "complete": False,
                                      "streams": [{"stream": "github:a/b:commits", "status": "running", "pages": 1,
                                                   "fetched": 5, "persisted": 3, "errors": []}]})


def test_sync_mode_selection(home, monkeypatch):
    assert sync.sync_mode() == "background"
    monkeypatch.setenv("VERCEL", "1")
    assert sync.sync_mode() == "inline" and isinstance(state.backend(), state.Neo4jState)  # Vercel defaults
    monkeypatch.setenv("HACKFRONT_SYNC", "background")
    assert sync.sync_mode() == "background"
    monkeypatch.setenv("HACKFRONT_SYNC", "nonsense")
    assert sync.sync_mode() == "inline"
    monkeypatch.setenv("HACKFRONT_STATE", "file")
    assert isinstance(state.backend(), state.FileState)  # an explicit choice still wins


def test_heartbeat_tells_a_live_job_in_another_instance_from_a_dead_one(home):
    slug = demo_workspace()
    persisted_running(slug, iso(3))  # another instance refreshed its heartbeat 3 s ago: alive
    live = sync.sync_status(slug)
    assert live["state"] == "running" and live["totals"]["persisted"] == 3 and "error" not in live
    with pytest.raises(RuntimeError, match="already running"):
        sync._prepare(slug, "standard")  # a second instance must not start a duplicate

    persisted_running(slug, iso(120))  # owner went away
    dead = sync.sync_status(slug)
    assert dead["state"] == "failed" and dead["error"] == "interrupted" and dead["streams"][0]["status"] == "failed"
    job, _ = sync._prepare(slug, "standard")  # and a new run may start
    assert job.status["state"] == "running"

    sync._jobs.clear()
    state.backend().write_sync(slug, {"state": "running", "streams": [], "complete": False})  # no heartbeat at all
    assert sync.sync_status(slug)["state"] == "failed"


def test_inline_run_returns_final_status_and_survives_a_fresh_process(home, db):
    slug = demo_workspace()
    final = sync.run_sync_inline(slug)
    assert final["state"] == "done" and final["complete"] and final["graph"]["artifacts"] > 0
    assert all(s["status"] == "done" for s in final["streams"]) and final["heartbeat"]
    sync._jobs.clear()  # another instance has no memory of the job: it reads the persisted status
    again = sync.sync_status(slug)
    assert again["state"] == "done" and again["complete"] and again["totals"] == final["totals"]


def test_another_instance_sees_live_progress_while_the_inline_request_is_open(home, db, monkeypatch):
    import threading

    from hackfront.ingest.storage.neo4j import Neo4jStore

    slug = demo_workspace()
    reached, release, writes, out = threading.Event(), threading.Event(), [], {}
    original = Neo4jStore.write_artifact

    def slow(self, artifact):
        result = original(self, artifact)
        writes.append(1)
        if len(writes) == 4:
            reached.set()
            assert release.wait(30)
        return result

    monkeypatch.setattr(Neo4jStore, "write_artifact", slow)
    worker = threading.Thread(target=lambda: out.update(final=sync.run_sync_inline(slug)))
    worker.start()
    assert reached.wait(30)
    sync._jobs.clear()  # the poll below is "another instance": no memory of the job, only the shared state
    for _ in range(40):  # the job is parked inside a write; throttled progress is flushed within about a second
        mid = sync.sync_status(slug)
        if mid["totals"]["persisted"] >= 3:
            break
        time.sleep(0.25)
    assert mid["state"] == "running" and mid["totals"]["persisted"] >= 3 and mid["streams"][0]["status"] == "running"
    with pytest.raises(RuntimeError, match="already running"):
        sync._prepare(slug, "standard")  # and it refuses a duplicate start
    release.set()
    worker.join(60)
    assert out["final"]["state"] == "done" and out["final"]["complete"]


def test_time_budget_stops_cleanly_without_an_error_flood(home, db):
    slug = demo_workspace()
    final = sync.run_sync_inline(slug, budget=1e-9)  # already spent when the first page is requested
    assert final["state"] == "done" and not final["complete"] and final["totals"]["persisted"] == 0
    assert final["streams"] and all(s["status"] == "incomplete" for s in final["streams"])
    for s in final["streams"]:
        assert [e["type"] for e in s["errors"]] == ["TimeBudget"]  # exactly one clear error per stream
    assert "time limit" in final["streams"][0]["errors"][0]["message"]


def test_budget_hit_midway_keeps_what_was_stored(home, db, monkeypatch):
    slug = demo_workspace()
    real, calls = sync._Job.expired, {"n": 0}

    def expired(self):
        calls["n"] += 1
        return real(self) or calls["n"] > 12  # let the first streams finish, then run out of time

    monkeypatch.setattr(sync._Job, "expired", expired)
    final = sync.run_sync_inline(slug, budget=3600)
    statuses = {s["status"] for s in final["streams"]}
    assert "done" in statuses and "incomplete" in statuses and not final["complete"]
    assert final["totals"]["persisted"] > 0 and final["totals"]["errors"] <= len(final["streams"])


def test_api_inline_mode_holds_the_request_and_returns_the_final_status(home, db, monkeypatch):
    monkeypatch.setenv("HACKFRONT_SYNC", "inline")
    slug = demo_workspace()
    client = TestClient(app)
    r = client.post(f"/api/w/{slug}/sync", json={"mode": "standard"})
    assert r.status_code == 200 and r.json()["state"] == "done" and r.json()["complete"]
    assert client.get(f"/api/w/{slug}/sync").json()["state"] == "done"

    monkeypatch.setenv("HACKFRONT_SYNC", "background")
    started = client.post(f"/api/w/{slug}/sync", json={"mode": "standard"})
    assert started.status_code == 202 and started.json()["state"] == "running"
    for _ in range(240):
        if client.get(f"/api/w/{slug}/sync").json()["state"] != "running":
            break
        time.sleep(0.25)
    assert client.get(f"/api/w/{slug}/sync").json()["complete"]


def test_one_shared_driver_per_process_and_close_is_a_noop(home, db):
    first = config.neo4j_driver()
    assert config.neo4j_driver() is first
    first.close()  # handlers call this after every request
    records, _, _ = first.execute_query("RETURN 1 AS n")  # still usable
    assert records[0]["n"] == 1
