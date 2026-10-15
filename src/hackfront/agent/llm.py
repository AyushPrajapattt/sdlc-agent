"""Provider layer over the OpenAI SDK (Azure Foundry and Sarvam are both OpenAI-compatible). Clients are lazy."""

from __future__ import annotations

import json
import os
import re
from contextvars import ContextVar
from urllib.parse import urlsplit

from pydantic import ValidationError

from .. import config

PROVIDERS = {
    "azure": {"key": "AZURE_FOUNDRY_API_KEY", "model": "Kimi-K2.5"},
    "sarvam": {"key": "SARVAM_API_KEY", "model": "sarvam-105b"},  # alternative: sarvam-30b
}
SARVAM_URL = "https://api.sarvam.ai/v1/"
MAX_TOKENS = 16000  # Sarvam spends part of this on reasoning_content, which we ignore
_clients: dict = {}  # provider -> client; rebuilt when credentials change; tests inject fakes here
_creds: dict = {}  # provider -> (credentials, client) it was built with
_workspace: ContextVar[str | None] = ContextVar("llm_workspace", default=None)


def foundry_base_url(endpoint: str) -> str:
    """Any URL Foundry shows (project, /models, /openai/deployments/...?api-version=) -> <resource root>/openai/v1/."""
    parts = urlsplit(endpoint.strip())
    if parts.netloc.endswith(".models.ai.azure.com"):  # serverless (pay-as-you-go) endpoint
        return f"{parts.scheme}://{parts.netloc}/v1/"
    return f"{parts.scheme}://{parts.netloc}/openai/v1/"


def set_workspace(slug: str | None) -> None:
    """Resolve credentials from this workspace's store (env fallback); None = environment only."""
    _workspace.set(slug)


def _setting(key: str) -> str:
    """A config.SECRETS key: workspace store then env when a workspace is set, else env only."""
    slug = _workspace.get()
    value = config.get_secret(slug, key) if slug else os.environ.get(config.SECRETS[key][0])
    return (value or "").strip()


def _key(provider: str) -> str:
    return _setting(f"{provider}_key")


def default_provider() -> str:
    chosen = _setting("llm_provider")
    return chosen or next((n for n in PROVIDERS if _key(n)), "azure")


def model_for(provider: str, model: str | None = None) -> str:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; choose one of {sorted(PROVIDERS)}")
    if model:
        return model
    # llm_model names a model for the default provider only; another provider uses its own default.
    configured = _setting("llm_model") if provider == default_provider() else ""
    return configured or PROVIDERS[provider]["model"]


def providers(workspace: str | None = None) -> list[dict]:
    token = _workspace.set(workspace) if workspace else None
    try:
        return [{"name": n, "model": model_for(n), "configured": bool(_key(n))} for n in PROVIDERS]
    finally:
        if token:
            _workspace.reset(token)


def client(provider: str):
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; choose one of {sorted(PROVIDERS)}")
    built = _creds.get(provider)  # (credentials, client) of the client we built
    if provider in _clients and (built is None or built[1] is not _clients[provider]):
        return _clients[provider]  # injected (tests): not ours, no credentials to compare
    key = _key(provider)
    if not key:
        raise RuntimeError(f"provider {provider} is not configured: set {PROVIDERS[provider]['key']}")
    endpoint = _setting("azure_endpoint") if provider == "azure" else ""
    creds = (key, endpoint)
    if built is None or built[0] != creds or provider not in _clients:
        from openai import OpenAI

        if provider == "azure":
            if not endpoint:
                raise RuntimeError("provider azure is not configured: set AZURE_FOUNDRY_ENDPOINT")
            url, headers = foundry_base_url(endpoint), {"api-key": key}
        else:
            url, headers = SARVAM_URL, {"api-subscription-key": key}
        # The SDK sends Authorization: Bearer; each provider also reads its own header.
        _clients[provider] = OpenAI(base_url=url, api_key=key, default_headers=headers, timeout=180)
        _creds[provider] = (creds, _clients[provider])
    return _clients[provider]


def ping(provider: str) -> str:
    """One tiny completion; returns reply text or raises RuntimeError with a message safe to show (no keys, no bodies)."""
    try:
        resp = client(provider).chat.completions.create(
            model=model_for(provider), messages=[{"role": "user", "content": "Reply with: ok"}], max_tokens=32)
        return clean(resp.choices[0].message.content) or "ok"
    except (RuntimeError, ValueError):
        raise  # our own messages (not configured / unknown provider)
    except Exception as error:
        status = getattr(error, "status_code", None)
        raise RuntimeError(f"{provider} rejected the request (HTTP {status})" if status
                           else f"could not reach {provider}") from None


def clean(text: str | None) -> str:
    return re.sub(r"<think>.*?</think>", "", text or "", flags=re.DOTALL).strip()


def structured(provider: str, template: str, schema, _model: str | None = None, **fields):
    """One structured LLM call returning a validated pydantic instance.

    Schema goes in the prompt and output is validated locally (no dependence on json_schema support).
    One repair round-trip on invalid JSON.
    """
    model = model_for(provider, _model)
    messages = [{"role": "user", "content": template.format(**fields)
                 + "\n\nRespond with ONLY a JSON object (no prose, no code fences) matching this JSON Schema:\n"
                 + json.dumps(schema.model_json_schema())}]
    text = ""
    for _ in range(2):
        resp = client(provider).chat.completions.create(model=model, messages=messages, max_tokens=MAX_TOKENS)
        text = clean(resp.choices[0].message.content)
        try:
            return schema.model_validate_json(text[text.find("{"): text.rfind("}") + 1])
        except ValidationError as error:
            messages += [{"role": "assistant", "content": text},
                         {"role": "user", "content": f"That JSON was invalid: {error}. Return the corrected JSON only."}]
    raise RuntimeError(f"{model} did not return valid {schema.__name__}: {text[:200]}")
