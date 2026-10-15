"""Demo workspace -> real Neo4j (test DB) -> agent with a REAL LLM provider (AC-6, AC-7, AC-8, AC-9).

Skipped per provider when its API key is not configured. Run: uv run pytest tests/e2e -q
Select providers with HACKFRONT_E2E_PROVIDERS=azure,sarvam (default: every configured one).
"""

import json
import os
from pathlib import Path

import pytest

from hackfront import config
from hackfront.ingest.demo import DEMO_WORKSPACE
from hackfront.ingest.sync import sync_workspace

CASES = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))
config.load_env()
KEYS = {"azure": "AZURE_FOUNDRY_API_KEY", "sarvam": "SARVAM_API_KEY"}
PROVIDERS = [p for p in os.environ.get("HACKFRONT_E2E_PROVIDERS", ",".join(KEYS)).split(",") if p]


@pytest.fixture(scope="module")
def graph(neo4j_test_driver):
    from tests.conftest import TEST_AUTH, TEST_URI

    mp = pytest.MonkeyPatch()
    for k, v in (("NEO4J_URI", TEST_URI), ("NEO4J_USERNAME", TEST_AUTH[0]), ("NEO4J_PASSWORD", TEST_AUTH[1])):
        mp.setenv(k, v)
    from hackfront.ingest.storage.neo4j.schema import initialize_schema

    neo4j_test_driver.execute_query("MATCH (n) DETACH DELETE n")
    initialize_schema(neo4j_test_driver)
    sync_workspace(DEMO_WORKSPACE, demo=True)
    yield neo4j_test_driver
    mp.undo()


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case(graph, provider, case):
    from hackfront import agent

    if not os.environ.get(KEYS[provider]):
        pytest.skip(f"{KEYS[provider]} not set")
    events = list(agent.run(case["question"], mode=case["mode"], provider=provider, driver=graph))
    assert events[-1]["event"] == "answer", events[-1]
    answer, evidence = events[-1]["answer"], events[-1]["evidence"]
    cited = answer["citations"]

    urls = {n["url"] for n in evidence["nodes"]}
    assert set(cited) <= urls, "citation outside retrieved evidence (AC-8)"
    if case.get("not_established"):
        assert answer["confidence"] == "low", answer  # AC-7
        return
    for needle in case["cites_all"]:
        assert any(needle in url for url in cited), f"missing citation {needle}: {cited}"
    text = answer["answer"].lower()
    assert any(m.lower() in text for m in case["answer_mentions_any"]), answer["answer"]
    assert answer["confidence"] in ("medium", "high"), answer
