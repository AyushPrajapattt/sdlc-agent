"""AC-2/AC-3: the demo workspace yields full evidence chains and re-syncing is idempotent."""

from hackfront.ingest.demo import DEMO_WORKSPACE
from hackfront.ingest.sync import graph_counts, sync_workspace

PR218 = "github:acme-demo%2Fshop:pull_request:218"
PAY412 = "jira:PAY:issue:PAY-412"


def _use_test_db(monkeypatch):
    from tests.conftest import TEST_AUTH, TEST_URI

    monkeypatch.setenv("NEO4J_URI", TEST_URI)
    monkeypatch.setenv("NEO4J_USERNAME", TEST_AUTH[0])
    monkeypatch.setenv("NEO4J_PASSWORD", TEST_AUTH[1])


def _edges(driver):
    records, _, _ = driver.execute_query(
        "MATCH (a:Artifact)-[r]->(b:Artifact) RETURN a.canonical_id AS a, type(r) AS t, r.origin AS o, b.canonical_id AS b")
    return {(r["a"], r["t"], r["o"], r["b"]) for r in records}


def test_demo_chain_and_idempotency(clean_graph, monkeypatch):
    _use_test_db(monkeypatch)
    first = sync_workspace(DEMO_WORKSPACE, demo=True)
    assert all(s["complete"] and not s["errors"] for s in first), first
    counts, edges = graph_counts(), _edges(clean_graph)

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
    assert counts["stubs"] >= 0 and counts["by_provider"].keys() == {"github", "jira", "slack"}

    sync_workspace(DEMO_WORKSPACE, demo=True)
    assert graph_counts() == counts and _edges(clean_graph) == edges
