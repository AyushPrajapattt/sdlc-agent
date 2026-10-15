"""Shared fixtures. Neo4j-backed tests use the throwaway `neo4j-test` service (bolt 7689) and are
skipped when it is not running. They WIPE all Artifact nodes — never point them at the dev graph."""

import os

import pytest

TEST_URI = os.environ.get("NEO4J_TEST_URI", "bolt://localhost:7689")
TEST_AUTH = (os.environ.get("NEO4J_TEST_USER", "neo4j"), os.environ.get("NEO4J_TEST_PASSWORD", "hackfront-test"))


@pytest.fixture(scope="session")
def neo4j_test_driver():
    from neo4j import GraphDatabase

    try:
        driver = GraphDatabase.driver(TEST_URI, auth=TEST_AUTH)
        driver.verify_connectivity()
    except Exception as error:  # noqa: BLE001
        pytest.skip(f"test Neo4j not reachable at {TEST_URI}: {error}")
    yield driver
    driver.close()


@pytest.fixture
def clean_graph(neo4j_test_driver):
    """Empty graph + schema before each test."""
    from hackfront.ingest.storage.neo4j.schema import initialize_schema

    neo4j_test_driver.execute_query("MATCH (n) DETACH DELETE n")
    initialize_schema(neo4j_test_driver)
    return neo4j_test_driver
