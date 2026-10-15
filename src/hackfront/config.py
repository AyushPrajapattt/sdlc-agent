"""Environment and workspace configuration shared by ingest, agent and api."""

from __future__ import annotations

import json
import os
from pathlib import Path

HOME = Path(os.environ.get("HACKFRONT_HOME", Path.cwd()))
WORKSPACE_FILE = HOME / "workspace.json"

EMPTY_WORKSPACE = {
    "github": {"owner": "", "repos": []},
    "jira": {"site": "", "projects": []},
    "slack": {"workspace": "", "channels": []},
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


def validate_workspace(data: dict) -> dict:
    """Return a clean workspace dict or raise ValueError. Secrets never live here."""
    out = {}
    for section, shape in EMPTY_WORKSPACE.items():
        raw = data.get(section) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"{section} must be an object")
        clean = {}
        for key, default in shape.items():
            value = raw.get(key, default)
            if isinstance(default, list):
                if not isinstance(value, list) or not all(isinstance(v, str) and v.strip() for v in value):
                    raise ValueError(f"{section}.{key} must be a list of non-empty strings")
                value = [v.strip() for v in value]
            elif not isinstance(value, str):
                raise ValueError(f"{section}.{key} must be a string")
            else:
                value = value.strip()
            clean[key] = value
        out[section] = clean
    site = out["jira"]["site"]
    if site and not site.startswith("https://"):
        raise ValueError("jira.site must be an https URL")
    return out


def load_workspace() -> dict:
    if not WORKSPACE_FILE.exists():
        return json.loads(json.dumps(EMPTY_WORKSPACE))
    return validate_workspace(json.loads(WORKSPACE_FILE.read_text(encoding="utf-8")))


def save_workspace(data: dict) -> dict:
    clean = validate_workspace(data)
    WORKSPACE_FILE.write_text(json.dumps(clean, indent=2), encoding="utf-8")
    return clean
