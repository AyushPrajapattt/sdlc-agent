import pytest
from pydantic import BaseModel

from hackfront.agent import llm
from hackfront.agent.flow import extract_ids, extract_seeds


class Fake:
    def __init__(self, *replies):
        self.replies, self.calls = list(replies), []
        self.chat = self
        self.completions = self

    def create(self, **kw):
        self.calls.append(kw)
        msg = type("M", (), {"content": self.replies.pop(0)})
        return type("R", (), {"choices": [type("C", (), {"message": msg})]})


class Out(BaseModel):
    a: int


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    monkeypatch.setattr(llm, "_clients", {})
    for k in ("LLM_PROVIDER", "LLM_MODEL", "AZURE_FOUNDRY_API_KEY", "SARVAM_API_KEY", "AZURE_FOUNDRY_ENDPOINT"):
        monkeypatch.delenv(k, raising=False)


def test_providers_never_leak_keys_and_import_needs_no_env(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "sekret")
    got = {p["name"]: p for p in llm.providers()}
    assert got["sarvam"] == {"name": "sarvam", "model": "sarvam-105b", "configured": True}
    assert got["azure"] == {"name": "azure", "model": "Kimi-K2.5", "configured": False}
    assert "sekret" not in str(got)


def test_model_selection(monkeypatch):
    assert llm.model_for("azure") == "Kimi-K2.5" and llm.model_for("sarvam", "sarvam-30b") == "sarvam-30b"
    monkeypatch.setenv("LLM_PROVIDER", "sarvam")
    monkeypatch.setenv("LLM_MODEL", "sarvam-30b")
    assert llm.model_for("sarvam") == "sarvam-30b" and llm.model_for("azure") == "Kimi-K2.5"
    with pytest.raises(ValueError):
        llm.model_for("nope")


def test_client_headers_and_urls(monkeypatch):
    monkeypatch.setenv("SARVAM_API_KEY", "k1")
    c = llm.client("sarvam")
    assert str(c.base_url) == "https://api.sarvam.ai/v1/" and c.default_headers["api-subscription-key"] == "k1"
    assert c.auth_headers["Authorization"] == "Bearer k1"
    monkeypatch.setenv("AZURE_FOUNDRY_API_KEY", "k2")
    monkeypatch.setenv("AZURE_FOUNDRY_ENDPOINT", "https://r.services.ai.azure.com/models")
    a = llm.client("azure")
    assert str(a.base_url) == "https://r.services.ai.azure.com/openai/v1/" and a.default_headers["api-key"] == "k2"
    assert a.auth_headers["Authorization"] == "Bearer k2"


def test_unconfigured_provider_is_a_clear_error():
    with pytest.raises(RuntimeError, match="AZURE_FOUNDRY_API_KEY"):
        llm.client("azure")


def test_structured_strips_think_and_repairs(monkeypatch):
    fake = Fake('<think>{"a": "no"}</think>\nsure: {"a": "bad"}', 'x <think>\n</think>{"a": 7} done')
    monkeypatch.setitem(llm._clients, "sarvam", fake)
    assert llm.structured("sarvam", "hi {x}", Out, x=1).a == 7
    assert len(fake.calls) == 2 and "invalid" in fake.calls[1]["messages"][-1]["content"]
    assert fake.calls[0]["model"] == "sarvam-105b" and fake.calls[0]["max_tokens"] >= 16000


def test_structured_gives_up(monkeypatch):
    monkeypatch.setitem(llm._clients, "azure", Fake("nope", "still nope"))
    with pytest.raises(RuntimeError, match="did not return valid Out"):
        llm.structured("azure", "hi", Out)


def test_debug_seed_extraction():
    trace = ('Traceback (most recent call last):\n  File "/app/src/pay/gateway.py", line 88, in retry\n'
             '  File "/usr/lib/python3/site-packages/requests/api.py", line 1\n'
             'PaymentError: PAY-412 timeout, see PR #77 and UTF-8, C:\\work\\repo\\svc\\retry.ts')
    assert extract_seeds(trace) == [("file_history", "src/pay/gateway.py"), ("file_history", "repo/svc/retry.ts"),
                                    ("find_text", "PAY-412"), ("find_text", "#77")]
    assert extract_seeds("nothing here") == []


def test_extract_ids():
    assert extract_ids("why github:acme:commit:c1 and http://x") == ["github:acme:commit:c1"]
