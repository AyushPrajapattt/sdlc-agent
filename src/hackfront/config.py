"""Environment, workspaces and per-workspace secrets, shared by ingest, agent and api.

Layout (all under HOME/.hackfront, gitignored):
  workspaces/<slug>/workspace.json   targets only: no secrets
  workspaces/<slug>/secrets.json     API keys (write-only through the API; chmod 600 best effort)
  workspaces/<slug>/investigations/  stored investigations
  workspaces/<slug>/sync.json        last sync status
Environment variables (GITHUB_TOKEN, ...) remain a fallback for any secret not stored in the workspace.
Security is deliberately minimal (local single-user tool): secrets are never returned by the API, only a masked hint.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from urllib.parse import urlsplit

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


def neo4j_driver():
    """Verified Neo4j driver from NEO4J_URI/USERNAME/PASSWORD (read-only user recommended for the agent)."""
    from neo4j import GraphDatabase

    uri, user, password = (os.environ.get(k) for k in ("NEO4J_URI", "NEO4J_USERNAME", "NEO4J_PASSWORD"))
    if not all((uri, user, password)):
        raise RuntimeError("NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD must be set (see .env.example)")
    driver = GraphDatabase.driver(uri, auth=(user, password))
    driver.verify_connectivity()
    return driver


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
    while workspace_dir(slug).exists():
        slug, n = f"{base}-{n}", n + 1
    return slug


def create_workspace(name: str, *, demo: bool = False, slug: str | None = None) -> str:
    """Create an empty (or demo) workspace and return its slug."""
    name = name.strip()
    if not name:
        raise ValueError("workspace name is required")
    slug = check_slug(slug) if slug else slugify(name)
    if workspace_dir(slug).exists():
        raise ValueError("workspace already exists")
    workspace_dir(slug).mkdir(parents=True)
    save_workspace(slug, {**EMPTY_WORKSPACE, "name": name, "demo": demo})
    return slug


def list_workspaces() -> list[dict]:
    root = workspaces_dir()
    out = []
    for path in sorted(root.iterdir()) if root.is_dir() else []:
        if path.is_dir() and SLUG.fullmatch(path.name) and (path / "workspace.json").exists():
            try:
                ws = load_workspace(path.name)
            except (ValueError, LookupError):  # a corrupt file must not hide the other workspaces
                out.append({"slug": path.name, "name": path.name, "demo": False})
                continue
            out.append({"slug": path.name, "name": ws["name"] or path.name, "demo": ws["demo"]})
    return out


def delete_workspace(slug: str) -> None:
    """Remove config, secrets and stored investigations. Graph data is left in Neo4j (it is shared source evidence)."""
    if not workspace_dir(slug).exists():
        raise LookupError("workspace not found")
    shutil.rmtree(workspace_dir(slug))


def load_workspace(slug: str) -> dict:
    path = workspace_dir(slug) / "workspace.json"
    if not path.exists():
        raise LookupError("workspace not found")
    return validate_workspace(json.loads(path.read_text(encoding="utf-8")))


def save_workspace(slug: str, data: dict) -> dict:
    clean = validate_workspace(data)
    directory = workspace_dir(slug)
    directory.mkdir(parents=True, exist_ok=True)
    tmp = directory / "workspace.json.tmp"
    tmp.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    os.replace(tmp, directory / "workspace.json")
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
def _secrets_path(slug: str) -> Path:
    return workspace_dir(slug) / "secrets.json"


def _stored(slug: str) -> dict:
    path = _secrets_path(slug)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except ValueError:
        data = {}
    return data if isinstance(data, dict) else {}


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
    if not workspace_dir(slug).exists():
        raise LookupError("workspace not found")
    data = _stored(slug)
    for key, value in values.items():
        value = value.strip()
        if value:
            data[key] = value
        else:
            data.pop(key, None)
    path = _secrets_path(slug)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
    try:
        os.chmod(tmp, 0o600)  # best effort (no-op semantics on Windows)
    except OSError:
        pass
    os.replace(tmp, path)


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
