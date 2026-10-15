import pytest

from hackfront.agent import harness as H
from hackfront.agent import text2cypher as T

from .conftest import cid

GOOD = ("MATCH (i:Artifact {record_kind:'issue'})<-[:REFERENCES]-(p:Artifact {record_kind:'pull_request'})"
        "-[:CONTAINS]->(c:Artifact) WHERE toLower(i.title) CONTAINS 'pay-412' RETURN p, c")


@pytest.mark.parametrize("bad", [
    "CREATE (n:X) RETURN n", "MATCH (n) DETACH DELETE n RETURN 1", "MATCH (n) SET n.x=1 RETURN n",
    "MATCH (n) REMOVE n.x RETURN n", "MERGE (n:X) RETURN n", "DROP INDEX x", "LOAD CSV FROM 'x' AS r RETURN r",
    "MATCH (n) FOREACH (x IN [1] | CREATE (:Y)) RETURN n", "CALL db.labels()", "RETURN apoc.version()",
    "CALL dbms.listConfig() YIELD name RETURN name", "USING PERIODIC COMMIT RETURN 1",
    "MATCH (n) RETURN n; MATCH (m) RETURN m", "MATCH (n {canonical_id: $id}) RETURN n", "MATCH (n) WHERE true",
    "MATCH (n) RETURN n // hi", "create (n) return n", "MATCH (n) RETURN n UNION MATCH (m) RETURN m", "",
])
def test_validator_rejects(bad):
    with pytest.raises(H.HarnessError):
        T.validate(bad)


def test_validator_accepts_and_caps_limit():
    assert T.validate(GOOD).endswith("LIMIT 25")
    assert T.validate(GOOD + " LIMIT 5;").endswith("LIMIT 5")
    assert T.validate(GOOD + " LIMIT 5000").endswith("LIMIT 25")
    assert "LIMIT 25" in T.validate("MATCH (n) WHERE n.title CONTAINS 'set create delete' RETURN n")  # literals ignored


def test_candidate_ids():
    rows = [{"p": {"canonical_id": "a:b:c:d", "title": "x"}, "n": 3, "l": ["e:f:g:h"]}, {"s": "a:b:c:d"}]
    assert T.candidate_ids(rows) == ["a:b:c:d", "e:f:g:h"]


def harness(graph, queries):
    queries = list(queries)
    calls = []

    def gen(q, err):
        calls.append(err)
        return queries.pop(0)

    return H.Harness(graph, cypher_llm=gen), calls


def test_cypher_query_hydrates_standard_rows_and_marks_seen(graph):
    h, _ = harness(graph, [GOOD])
    rows = h.call("cypher_query", "which PRs and commits relate to PAY-412")
    assert {r["id"] for r in rows} == {cid("pull_request", "pr1"), cid("commit", "c1")}
    assert set(rows[0]) >= {"id", "kind", "title", "text", "url", "time", "paths"} and len(rows[0]["text"]) <= 600
    assert h.call("neighbors", cid("commit", "c1"))  # ids found this way count as seen
    assert h.cypher_log[0]["error"] is None and "PAY-412".lower() in h.cypher_log[0]["cypher"]


def test_stubs_are_never_hydrated(graph):
    h, _ = harness(graph, ["MATCH (n:Artifact) WHERE n.canonical_id CONTAINS 'stubx' RETURN n"])
    assert h.call("cypher_query", "stubs") == []


def test_repair_path_bad_then_good(graph):
    h, calls = harness(graph, ["MATCH (n:Artifact RETURN n", GOOD])
    rows = h.call("cypher_query", "q")
    assert rows and calls[0] is None and calls[1]  # second attempt got the error text
    assert h.cypher_log[0]["error"] is None


def test_gives_up_after_two_repairs_without_raising(graph):
    h, calls = harness(graph, ["CREATE (n:X) RETURN n"] * 3)
    assert h.call("cypher_query", "q") == [] and len(calls) == 3
    assert h.cypher_log[0]["error"]


def test_write_attempt_never_changes_graph(graph):
    count = lambda: graph.execute_query("MATCH (n) RETURN count(n) AS c").records[0]["c"]  # noqa: E731
    before = count()
    h, _ = harness(graph, ["MATCH (n:Artifact) SET n.title = 'pwned' RETURN n"] * 3)
    assert h.call("cypher_query", "q") == []
    assert count() == before
    assert graph.execute_query("MATCH (n {title: 'pwned'}) RETURN n").records == []


def test_cypher_query_unavailable_without_llm(graph):
    with pytest.raises(H.HarnessError):
        H.Harness(graph).call("cypher_query", "q")


import pytest


@pytest.mark.parametrize("q", [
    "SHOW SETTINGS YIELD name RETURN name",
    "TERMINATE TRANSACTIONS 'x' YIELD message RETURN message",
    "USE system MATCH (n) RETURN n",
    "INSERT (:X) RETURN 1",
    "MATCH (n) RETURN reduce(s='a', i IN range(1,22) | s + s)",
    "MATCH (n) RETURN range(1,3000000)",
])
def test_admin_and_size_bomb_queries_rejected(q):
    with pytest.raises(H.HarnessError):
        T.validate(q)


def test_plain_read_still_accepted():
    assert T.validate("MATCH (a:Artifact) RETURN a.canonical_id").endswith("LIMIT 25")


def test_out_of_scope_id_from_the_model_is_never_hydrated(graph):
    graph.execute_query("MATCH (a:Artifact {canonical_id: $id}) SET a.scope = 'other/ws'", id=cid("issue", "issue1"))
    q = "MATCH (n:Artifact) WHERE n.record_kind IN ['issue', 'pull_request'] RETURN n"
    h = H.Harness(graph, cypher_llm=lambda question, err: q, scopes=["acme"])
    rows = h.call("cypher_query", "issues and PRs")
    assert {r["id"] for r in rows} == {cid("pull_request", "pr1"), cid("issue", "issue2")}
    assert cid("issue", "issue1") not in h.seen
    assert H.Harness(graph, cypher_llm=lambda question, err: q, scopes=[]).call("cypher_query", "x") == []
