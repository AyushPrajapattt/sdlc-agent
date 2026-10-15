import pytest

from hackfront.agent import harness as H

from .conftest import cid


@pytest.fixture
def h(graph):
    return H.Harness(graph)


def ids(rows):
    return [r["id"] for r in rows]


def test_find_text_requires_all_words_and_skips_stubs(h):
    rows = h.call("find_text", "Gateway retries")
    assert set(ids(rows)) == {cid("issue", "issue1"), cid("thread", "thread1"), cid("commit", "c1")}
    assert h.call("find_text", "retries banana") == []
    assert all(i != cid("misc", "stubx") for i in ids(h.call("find_text", "x")))
    row = h.call("find_text", "PAY-412 storm")[0]
    assert row["id"] == cid("pull_request", "pr1") and len(row["text"]) == 600
    assert set(row) >= {"id", "kind", "title", "text", "url", "time", "paths"}


def test_file_history_chronological(h):
    rows = h.call("file_history", "pay/gateway.py")
    assert ids(rows) == [cid("commit", "c2"), cid("commit", "c1")]
    assert h.call("file_history", "src\\pay\\retry.py")[0]["id"] == cid("commit", "c1")


def test_neighbors_have_via_and_skip_stubs(h):
    h.see([cid("commit", "c1")])
    rows = {r["id"]: r for r in h.call("neighbors", cid("commit", "c1"))}
    assert set(rows) == {cid("pull_request", "pr1"), cid("commit", "c2")}  # stub c0 excluded
    via = rows[cid("pull_request", "pr1")]["via"]
    assert via == {"rel": "CONTAINS", "origin": "structural", "from": cid("pull_request", "pr1")}


def test_evidence_chain_depth_parents_and_stub_traversal(h):
    h.see([cid("pull_request", "pr1")])
    rows = {r["id"]: r for r in h.call("evidence_chain", cid("pull_request", "pr1"))}
    assert rows[cid("commit", "c1")]["hops"] == 1
    assert rows[cid("issue", "issue1")]["hops"] == 1
    assert rows[cid("message", "msg1")]["hops"] == 2  # pr -> thread <- message
    assert rows[cid("issue", "issue2")]["hops"] == 2  # traversed THROUGH the stub
    assert cid("misc", "stubx") not in rows and cid("pull_request", "pr1") not in rows
    assert cid("commit", "c2") not in rows  # only reachable via a $.parents edge


def test_get_returns_full_text(h):
    h.see([cid("pull_request", "pr1")])
    assert len(h.call("get", cid("pull_request", "pr1"))[0]["text"]) > 700


def test_unseen_or_malformed_ids_never_reach_db(h, monkeypatch):
    monkeypatch.setattr(H, "execute", lambda *a, **k: pytest.fail("DB hit"))
    for tool in ("neighbors", "evidence_chain", "get"):
        with pytest.raises(H.HarnessError, match="not seen"):
            h.call(tool, cid("pull_request", "pr1"))
        with pytest.raises(H.HarnessError, match="invalid characters"):
            h.call(tool, "x}) DETACH DELETE (n //")


def test_arg_and_tool_validation(h):
    for tool, arg in [("drop_db", "x"), ("find_text", ""), ("find_text", "x" * 201), ("find_text", 5),
                      ("file_history", "a\x00b"), ("find_text", "...")]:
        with pytest.raises(H.HarnessError):
            h.call(tool, arg)


def test_rows_seen_after_call_unlock_ids(h):
    row = h.call("find_text", "PAY-412 storm")[0]
    assert h.call("neighbors", row["id"])


def test_seed_ids_count_as_seen(h):
    h.see([cid("issue", "issue1")])
    assert h.call("neighbors", cid("issue", "issue1"))


def test_edges_among(h):
    edges = h.edges_among([cid("pull_request", "pr1"), cid("commit", "c1"), cid("issue", "issue1")])
    assert {(e["rel"], e["origin"]) for e in edges} == {("CONTAINS", "structural"), ("REFERENCES", "structural")}
    assert h.edges_among([]) == []


def test_selfcheck_ok_and_fails_on_bad_template(graph, monkeypatch):
    H._checked.discard(id(graph))
    H.selfcheck(graph)
    assert id(graph) in H._checked
    H._checked.discard(id(graph))
    monkeypatch.setitem(H.CYPHER, "get", "MATCH (a:Artifact RETURN a")
    with pytest.raises(RuntimeError, match="get failed EXPLAIN"):
        H.selfcheck(graph)
    H._checked.discard(id(graph))


def test_executor_refuses_writes(graph):
    for q in ("CREATE (:Artifact {canonical_id: 'evil'})", "MATCH (n) DETACH DELETE n", "MATCH (n) SET n.x = 1"):
        with pytest.raises(H.HarnessError):
            H.execute(graph, q)
    assert graph.execute_query("MATCH (n) RETURN count(n) AS c").records[0]["c"] > 0


def test_server_rejects_write_in_read_route(graph):
    """Second layer: even bypassing the static check, read routing must not write."""
    from neo4j import Query

    with pytest.raises(Exception):  # noqa: B017
        graph.execute_query(Query("CREATE (:Artifact {canonical_id: 'evil'})"), routing_="r", database_=H.neo4j_database())
    assert graph.execute_query("MATCH (n {canonical_id: 'evil'}) RETURN n").records == []
