from dataclasses import replace

from hackfront.ingest.contracts import RelationshipKind, SourceIdentity, SourceReference
from hackfront.ingest.extraction.links import LinkConfig, add_text_references
from hackfront.ingest.storage.neo4j import Neo4jStore
from tests.ingest.unit.test_links import art

CFG = LinkConfig(frozenset({"PAY"}), "acme")


def edges(driver):
    records, _, _ = driver.execute_query(
        "MATCH (:Artifact)-[r]->(b:Artifact) RETURN r.origin AS o, b.canonical_id AS b")
    return {(r["o"], r["b"]) for r in records}


def test_editing_text_removes_stale_text_edges_but_keeps_structural(clean_graph):
    store = Neo4jStore(clean_graph)
    structural = SourceReference(SourceIdentity("github", "acme/shop", "commit", "c" * 40), RelationshipKind.CONTAINS, "$.x")
    pr = replace(art("github", "acme/shop", "pull_request", "1", "Fixes PAY-1"), references=(structural,))
    store.write_artifact(add_text_references(pr, CFG))
    assert edges(clean_graph) == {("structural", "github:acme%2Fshop:commit:" + "c" * 40), ("text", "jira:PAY:issue:PAY-1")}

    edited = replace(pr, text="Fixes PAY-2")  # the author corrected the ticket
    store.write_artifact(add_text_references(edited, CFG))
    assert edges(clean_graph) == {("structural", "github:acme%2Fshop:commit:" + "c" * 40), ("text", "jira:PAY:issue:PAY-2")}
