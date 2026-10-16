"""Environment, workspaces and per-workspace secrets, shared by ingest, agent and api.

Storage is pluggable (see state.py): HACKFRONT_STATE=file (default; HOME/.hackfront/workspaces/<slug>/...) or neo4j
(stateless hosting; keys encrypted with HACKFRONT_SECRET_KEY). This module holds the validation and masking logic only.
Environment variables (GITHUB_TOKEN, ...) remain a fallback for any secret not stored in the workspace.
Security is deliberately minimal (single-user tool): secrets are never returned by the API, only a masked hint.
"""

from __future__ import annotations

import os
import re
from pathlib import Path
from urllib.parse import urlsplit

from . import state

HOME = Path(os.environ.get("HACKFRONT_HOME", Path.cwd()))
SLUG = re.compile(r"[a-z0-9][a-z0-9-]{0,39}")

EMPTY_WORKSPACE = {
    "name": "",
    "demo": False,
    "github": {"owner": "", "repos": []},
    "jira": {"site": "", "projects": []},
    "slack": {"workspace": "", "channels": [], "channel_names": {}, "users": {}},
}

# secret key -> (environment fallback, is_secret). Non-secrets (endpoint, provider, model, jira email) may be shown.
SECRETS = {
    "github_token": ("GITHUB_TOKEN", True),
    "jira_email": ("JIRA_EMAIL", False),
    "jira_token": ("JIRA_API_TOKEN", True),
    "slack_token": ("SLACK_BOT_TOKEN", True),
    "azure_endpoint": ("AZURE_FOUNDRY_ENDPOINT", False),
    "azure_key": ("AZURE_FOUNDRY_API_KEY", True),
    "sarvam_key": ("SARVAM_API_KEY", True),
    "llm_provider": ("LLM_PROVIDER", False),
    "llm_model": ("LLM_MODEL", False),
}


def load_env(path: Path | None = None) -> None:
    """Load KEY=VALUE lines from .env without overriding real environment variables."""
    path = path or HOME / ".env"
    if not path.exists():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            key, value = line.split("=", 1)
            if value.strip():
                os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


def neo4j_database() -> str:
    return os.environ.get("NEO4J_DATABASE", "neo4j")


_shared_drivers: dict = {}


class _SharedDriver:
    """Process-wide driver. Handlers call close() after each request; here that is a no-op, so a serverless instance
    (or a long-lived one) opens ONE TLS connection pool to Neo4j instead of one per request."""

    def __init__(self, driver):
        self._driver = driver

    def close(self) -> None:
        pass

    def __getattr__(self, name):
        return getattr(self._driver, name)


def neo4j_driver():
    """Shared Neo4j driver from NEO4J_URI/USERNAME/PASSWORD, connectivity verified once per process."""
    from neo4j import GraphDatabase

    key = tuple(os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"))
    if not all(key):
        raise RuntimeError("NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD must be set (see .env.example)")
    if key not in _shared_drivers:
        driver = GraphDatabase.driver(key[0], auth=(key[1], key[2]))
        try:
            driver.verify_connectivity()
        except Exception:
            driver.close()
            raise
        _shared_drivers[key] = _SharedDriver(driver)
    return _shared_drivers[key]


# ---------------------------------------------------------------- workspaces
def check_slug(slug: str) -> str:
    if not isinstance(slug, str) or not SLUG.fullmatch(slug):
        raise ValueError("invalid workspace id")
    return slug


def workspaces_dir() -> Path:
    return HOME / ".hackfront" / "workspaces"


def workspace_dir(slug: str) -> Path:
    return workspaces_dir() / check_slug(slug)


def validate_workspace(data: dict) -> dict:
    """Return a clean workspace dict or raise ValueError. Secrets never live here."""
    out = {"name": str(data.get("name") or "").strip()[:80], "demo": bool(data.get("demo", False))}
    for section, shape in EMPTY_WORKSPACE.items():
        if section in ("name", "demo"):
            continue
        raw = data.get(section) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{section} must be an object")
        clean = {}
        for key, default in shape.items():
            value = raw.get(key, default)
            if isinstance(default, list):
                if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
                    raise ValueError(f"{section}.{key} must be a list of non-empty strings")
                value = list(dict.fromkeys(v.strip() for v in value))
            elif isinstance(default, dict):
                if not isinstance(value, dict) or not all(isinstance(k, str) and isinstance(v, str) for k, v in value.items()):
                    raise ValueError(f"{section}.{key} must map strings to strings")
                value = dict(value)
            elif not isinstance(value, str):
                raise ValueError(f"{section}.{key} must be a string")
            else:
                value = value.strip()
            clean[key] = value
        out[section] = clean
    site = out["jira"]["site"]
    if site:
        host = urlsplit(site).hostname or ""
        if not site.startswith("https://") or not host.endswith(".atlassian.net"):
            raise ValueError("jira.site must be an https Jira Cloud URL (*.atlassian.net); the API token is sent to this host")
    return out


def slugify(name: str) -> str:
    base = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:30] or "workspace"
    slug, n = base, 2
    while state.backend().exists(slug):
        slug, n = f"{base}-{n}", n + 1
    return slug


def create_workspace(name: str, *, demo: bool = False, slug: str | None = None) -> str:
    """Create an empty (or demo) workspace and return its slug."""
    name = name.strip()
    if not name:
        raise ValueError("workspace name is required")
    slug = check_slug(slug) if slug else slugify(name)
    if state.backend().exists(slug):
        raise ValueError("workspace already exists")
    save_workspace(slug, {**EMPTY_WORKSPACE, "name": name, "demo": demo})
    return slug


def list_workspaces() -> list[dict]:
    out = []
    for slug in state.backend().slugs():
        try:
            ws = load_workspace(slug)
        except (ValueError, LookupError):  # a corrupt record must not hide the other workspaces
            out.append({"slug": slug, "name": slug, "demo": False})
            continue
        out.append({"slug": slug, "name": ws["name"] or slug, "demo": ws["demo"]})
    return out


def delete_workspace(slug: str) -> None:
    """Remove config, keys, stored investigations and sync status. Graph data is left in Neo4j (shared source evidence)."""
    check_slug(slug)
    if not state.backend().exists(slug):
        raise LookupError("workspace not found")
    state.backend().delete(slug)


def load_workspace(slug: str) -> dict:
    raw = state.backend().read_workspace(check_slug(slug))
    if raw is None:
        raise LookupError("workspace not found")
    return validate_workspace(raw)


def save_workspace(slug: str, data: dict) -> dict:
    clean = validate_workspace(data)
    state.backend().write_workspace(check_slug(slug), clean)
    return clean


def scopes(slug: str) -> dict:
    """What this workspace may see: `owner/repo` names, Jira project keys, Slack channel ids."""
    ws = load_workspace(slug)
    owner = ws["github"]["owner"]
    return {
        "repos": [r if "/" in r else f"{owner}/{r}" for r in ws["github"]["repos"]],
        "jira": list(ws["jira"]["projects"]),
        "slack": list(ws["slack"]["channels"]),
    }


def names(slug: str) -> dict:
    """Display names learned from Slack: {'channels': {id: name}, 'users': {id: name}}."""
    s = load_workspace(slug)["slack"]
    return {"channels": s["channel_names"], "users": s["users"]}


# ---------------------------------------------------------------- secrets
def _stored(slug: str) -> dict:
    return state.backend().read_secrets(check_slug(slug))


def get_secret(slug: str, key: str) -> str | None:
    """Stored workspace value, else the environment fallback, else None."""
    if key not in SECRETS:
        raise KeyError(key)
    value = _stored(slug).get(key)
    if isinstance(value, str) and value:
        return value
    return os.environ.get(SECRETS[key][0]) or None


def set_secrets(slug: str, values: dict) -> None:
    """Partial update: a non-empty string sets a key, an empty string clears it. Unknown keys are rejected."""
    unknown = set(values) - set(SECRETS)
    if unknown:
        raise ValueError(f"unknown setting: {sorted(unknown)[0]}")
    if not all(isinstance(v, str) and len(v) <= 2000 and "\n" not in v and "\r" not in v for v in values.values()):
        raise ValueError("settings must be single-line strings")
    if not state.backend().exists(check_slug(slug)):
        raise LookupError("workspace not found")
    data = _stored(slug)
    for key, value in values.items():
        value = value.strip()
        if value:
            data[key] = value
        else:
            data.pop(key, None)
    state.backend().write_secrets(slug, data)


def secret_status(slug: str) -> dict:
    """Per key: {set, source: 'workspace'|'env'|None, value (non-secrets only), hint (masked, secrets only)}."""
    stored = _stored(slug)
    out = {}
    for key, (env, is_secret) in SECRETS.items():
        own = stored.get(key) if isinstance(stored.get(key), str) and stored.get(key) else None
        value = own or os.environ.get(env) or None
        entry = {"set": bool(value), "source": "workspace" if own else "env" if value else None}
        if value:
            if is_secret:
                entry["hint"] = ("••••" + value[-4:]) if len(value) >= 12 else "••••"
            else:
                entry["value"] = value
        out[key] = entry
    return out
