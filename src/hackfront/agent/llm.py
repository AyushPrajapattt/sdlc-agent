"""Provider layer over the OpenAI SDK (Azure Foundry and Sarvam are both OpenAI-compatible). Clients are lazy."""

from __future__ import annotations

import json
import os
import re
from urllib.parse import urlsplit

from pydantic import ValidationError

PROVIDERS = {
    "azure": {"key": "AZURE_FOUNDRY_API_KEY", "model": "Kimi-K2.5"},
    "sarvam": {"key": "SARVAM_API_KEY", "model": "sarvam-105b"},  # alternative: sarvam-30b
}
SARVAM_URL = "https://api.sarvam.ai/v1/"
MAX_TOKENS = 16000  # Sarvam spends part of this on reasoning_content, which we ignore
_clients: dict = {}  # provider -> client; tests inject fakes here


def foundry_base_url(endpoint: str) -> str:
    """Any URL Foundry shows (project, /models, /openai/deployments/...?api-version=) -> <resource root>/openai/v1/."""
    parts = urlsplit(endpoint.strip())
    if parts.netloc.endswith(".models.ai.azure.com"):  # serverless (pay-as-you-go) endpoint
        return f"{parts.scheme}://{parts.netloc}/v1/"
    return f"{parts.scheme}://{parts.netloc}/openai/v1/"


def default_provider() -> str:
    return os.environ.get("LLM_PROVIDER", "").strip() or "azure"


def model_for(provider: str, model: str | None = None) -> str:
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; choose one of {sorted(PROVIDERS)}")
    if model:
        return model
    # LLM_MODEL names a model for the default provider only; another provider uses its own default.
    env = os.environ.get("LLM_MODEL", "").strip() if provider == default_provider() else ""
    return env or PROVIDERS[provider]["model"]


def _key(provider: str) -> str:
    return os.environ.get(PROVIDERS[provider]["key"], "").strip()


def providers() -> list[dict]:
    return [{"name": n, "model": model_for(n), "configured": bool(_key(n))} for n in PROVIDERS]


def client(provider: str):
    if provider not in PROVIDERS:
        raise ValueError(f"unknown provider {provider!r}; choose one of {sorted(PROVIDERS)}")
    if provider not in _clients:
        key = _key(provider)
        if not key:
            raise RuntimeError(f"provider {provider} is not configured: set {PROVIDERS[provider]['key']}")
        from openai import OpenAI

        if provider == "azure":
            endpoint = os.environ.get("AZURE_FOUNDRY_ENDPOINT", "").strip()
            if not endpoint:
                raise RuntimeError("provider azure is not configured: set AZURE_FOUNDRY_ENDPOINT")
            url, headers = foundry_base_url(endpoint), {"api-key": key}
        else:
            url, headers = SARVAM_URL, {"api-subscription-key": key}
        # The SDK sends Authorization: Bearer; each provider also reads its own header.
        _clients[provider] = OpenAI(base_url=url, api_key=key, default_headers=headers, timeout=180)
    return _clients[provider]


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
