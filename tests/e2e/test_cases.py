"""Demo workspace -> real Neo4j (test DB) -> agent with a REAL LLM provider (AC-6, AC-7, AC-8, AC-9, AC-15).

Skipped per provider when its API key is not configured. Run: uv run pytest tests/e2e -q
Select providers with HACKFRONT_E2E_PROVIDERS=azure,sarvam (default: every configured one).
"""

import json
import os
import time
from pathlib import Path

import pytest

from hackfront import config
from hackfront.api.mapping import flat_scopes

CASES = json.loads((Path(__file__).parent / "cases.json").read_text(encoding="utf-8"))
config.load_env()
KEYS = {"azure": "AZURE_FOUNDRY_API_KEY", "sarvam": "SARVAM_API_KEY"}
PROVIDERS = [p for p in os.environ.get("HACKFRONT_E2E_PROVIDERS", ",".join(KEYS)).split(",") if p]


@pytest.fixture(scope="module")
def demo(neo4j_test_driver, tmp_path_factory):
    """A demo workspace synced through the real pipeline into the throwaway DB."""
    from tests.conftest import TEST_AUTH, TEST_URI

    from hackfront.ingest.demo import DEMO_WORKSPACE
    from hackfront.ingest.storage.neo4j.schema import initialize_schema
    from hackfront.ingest.sync import start_sync, sync_status

    mp = pytest.MonkeyPatch()
    mp.setattr(config, "HOME", tmp_path_factory.mktemp("home"))
    for k, v in (("NEO4J_URI", TEST_URI), ("NEO4J_USERNAME", TEST_AUTH[0]), ("NEO4J_PASSWORD", TEST_AUTH[1])):
        mp.setenv(k, v)
    neo4j_test_driver.execute_query("MATCH (n) DETACH DELETE n")
    initialize_schema(neo4j_test_driver)
    slug = config.create_workspace("Acme Demo", demo=True, slug="demo")
    config.save_workspace(slug, DEMO_WORKSPACE)
    start_sync(slug)
    for _ in range(120):
        status = sync_status(slug)
        if status["state"] != "running":
            break
        time.sleep(0.5)
    assert status["state"] == "done" and status["complete"], status
    yield slug
    mp.undo()


@pytest.mark.parametrize("provider", PROVIDERS)
@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
def test_case(demo, neo4j_test_driver, provider, case):
    from hackfront import agent

    if not os.environ.get(KEYS[provider]):
        pytest.skip(f"{KEYS[provider]} not set")
    scopes = flat_scopes(config.scopes(demo))
    events = list(agent.run(case["question"], mode=case["mode"], provider=provider, driver=neo4j_test_driver,
                            scopes=scopes, workspace=demo))
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


def test_other_workspace_sees_nothing(demo, neo4j_test_driver):
    """AC-15: a workspace with no connected scopes cannot retrieve the demo's evidence."""
    from hackfront import agent

    events = list(agent.run("Why are gateway retries capped at 3?", mode="why", driver=neo4j_test_driver,
                            scopes=[], workspace=None, provider="azure"))
    last = events[-1]
    assert last["event"] in ("answer", "error")
    if last["event"] == "answer":
        assert last["answer"]["citations"] == [] and last["evidence"]["nodes"] == []
