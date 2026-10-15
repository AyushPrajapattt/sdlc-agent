"""Workspaces, secrets, integration tests and discovery (docs/workbench-api.md). Owned by MVP-WS.

Every error message returned here is a fixed, safe string: no exception text, URLs, tokens or response bodies.
"""

from __future__ import annotations

import json
from typing import Literal

from fastapi import APIRouter, Body, HTTPException
from pydantic import BaseModel

from .. import config
from ..ingest.sources.github.client import GitHubClient
from ..ingest.sources.jira.client import JiraClient
from ..ingest.sources.slack.client import SlackClient

router = APIRouter()
Integration = Literal["github", "jira", "slack", "llm"]
LABEL = {"github": "GitHub", "jira": "Jira", "slack": "Slack"}
SECRET_KEYS = {
    "github": ["github_token"],
    "jira": ["jira_email", "jira_token"],
    "slack": ["slack_token"],
    "llm": ["azure_endpoint", "azure_key", "sarvam_key", "llm_provider", "llm_model"],
}
INDEXED_Q = ("MATCH (a:Artifact {record_kind: 'git_commit'}) WHERE NOT coalesce(a.is_stub, false) "
             "AND a.scope IN $repos RETURN DISTINCT a.scope AS scope")
ARTIFACTS_Q = ("MATCH (a:Artifact) WHERE NOT coalesce(a.is_stub, false) AND a.scope IN $scopes "
               "RETURN count(a) AS artifacts")
EDGES_Q = ("MATCH (a:Artifact)-[r]->(b:Artifact) WHERE NOT coalesce(a.is_stub, false) AND a.scope IN $scopes "
           "RETURN count(r) AS edges, count(DISTINCT CASE WHEN coalesce(b.is_stub, false) THEN b END) AS stubs")


class NewWorkspace(BaseModel):
    name: str
    demo: bool = False


def _workspace(slug: str) -> dict:
    try:
        return config.load_workspace(slug)
    except (LookupError, ValueError):
        raise HTTPException(404, "workspace not found") from None


def _safe(label: str, error: Exception) -> str:
    """Human message for an upstream failure; never the exception text (except Slack's identifier-checked code)."""
    status = getattr(error, "status", None)
    message = str(error)
    if status in (401, 403):
        return f"{label} rejected the credentials (HTTP {status})"
    if message.startswith("Slack API error: "):  # SlackClient only lets a bare identifier through
        return message
    if status:
        return f"{label} returned HTTP {status}"
    return "Network error" if not isinstance(error, ValueError) else f"{label} target is invalid"


class _Missing(Exception):
    """A credential or target is not saved; the message is safe to show."""


def _client(slug: str, ws: dict, which: str):
    if ws["demo"]:
        from ..ingest.demo import demo_clients  # lazy: demo data is only needed for demo workspaces

        return dict(zip(("github", "jira", "slack"), demo_clients()))[which]
    secret = lambda key: config.get_secret(slug, key)  # noqa: E731
    if which == "github":
        if not secret("github_token"):
            raise _Missing("GitHub token not saved")
        return GitHubClient(token=secret("github_token"))
    if which == "jira":
        if not secret("jira_token") or not secret("jira_email"):
            raise _Missing("Jira email and token not saved")
        if not ws["jira"]["site"]:
            raise _Missing("Jira site not set")
        return JiraClient(ws["jira"]["site"], secret("jira_token"), email=secret("jira_email"))
    if not secret("slack_token"):
        raise _Missing("Slack token not saved")
    return SlackClient(secret("slack_token"))


# ---------------------------------------------------------------- workspaces
def _last_sync(slug: str):
    try:
        data = json.loads((config.workspace_dir(slug) / "sync.json").read_text(encoding="utf-8"))
        return {"state": data["state"], "finished_at": data.get("finished_at")}
    except (OSError, ValueError, KeyError, TypeError):
        return None


@router.get("/api/workspaces")
def list_workspaces():
    out = []
    for row in config.list_workspaces():
        try:
            scopes = config.scopes(row["slug"])
        except (LookupError, ValueError):  # one corrupt workspace must not hide the others
            scopes = {"repos": [], "jira": [], "slack": []}
        row["connected"] = {"repos": len(scopes["repos"]), "jira": len(scopes["jira"]), "slack": len(scopes["slack"])}
        sync = _last_sync(row["slug"])
        if sync:
            row["last_sync"] = sync
        out.append(row)
    return out


@router.post("/api/workspaces", status_code=201)
def create_workspace(body: NewWorkspace):
    try:
        slug = config.create_workspace(body.name)
        if body.demo:
            from ..ingest.demo import DEMO_WORKSPACE

            config.save_workspace(slug, {**config.EMPTY_WORKSPACE, **DEMO_WORKSPACE,
                                         "name": body.name.strip(), "demo": True})
    except ValueError as error:
        raise HTTPException(422, str(error)) from None
    return {"slug": slug, "name": body.name.strip(), "demo": body.demo}


@router.delete("/api/workspaces/{ws}")
def delete_workspace(ws: str):
    try:
        config.delete_workspace(ws)
    except (LookupError, ValueError):
        raise HTTPException(404, "workspace not found") from None
    return {"ok": True}


# ---------------------------------------------------------------- workbench
def _graph_facts(scopes: dict) -> tuple[list[str], dict]:
    """(indexed repos, neo4j status) scoped to this workspace; any failure becomes empty/ok=false."""
    from neo4j import READ_ACCESS

    try:
        driver = config.neo4j_driver()
    except Exception:
        return [], {"ok": False}
    try:
        flat = [*scopes["repos"], *scopes["jira"], *scopes["slack"]]
        with driver.session(database=config.neo4j_database(), default_access_mode=READ_ACCESS) as session:
            try:
                indexed = {r["scope"] for r in session.run(INDEXED_Q, repos=scopes["repos"]).data()}
            except Exception:
                indexed = set()
            counts = {**session.run(ARTIFACTS_Q, scopes=flat).data()[0], **session.run(EDGES_Q, scopes=flat).data()[0]}
        return [r for r in scopes["repos"] if r in indexed], {"ok": True, "counts": counts}
    except Exception:
        return [], {"ok": False}
    finally:
        try:
            driver.close()
        except Exception:
            pass


@router.get("/api/w/{ws}/workbench")
def workbench(ws: str):
    cfg = _workspace(ws)
    scopes = config.scopes(ws)
    status = config.secret_status(ws)
    have = lambda key: bool(config.get_secret(ws, key))  # noqa: E731
    demo = cfg["demo"]
    configured = {
        "github": demo or (have("github_token") and bool(scopes["repos"])),
        "jira": demo or (have("jira_email") and have("jira_token") and bool(cfg["jira"]["site"]) and bool(scopes["jira"])),
        "slack": demo or (have("slack_token") and bool(scopes["slack"])),
        "llm": (have("azure_key") and have("azure_endpoint")) or have("sarvam_key"),
    }
    targets = {"github": len(scopes["repos"]), "jira": len(scopes["jira"]), "slack": len(scopes["slack"])}
    integrations = {}
    for name, keys in SECRET_KEYS.items():
        integrations[name] = {"configured": configured[name], "secrets": {k: status[k] for k in keys}}
        if name in targets:
            integrations[name]["targets"] = targets[name]
    indexed, neo4j = _graph_facts(scopes)
    try:
        from ..agent import llm

        providers = llm.providers(ws)
    except Exception:
        providers = []
    return {
        "workspace": {"slug": ws, "name": cfg["name"] or ws, "demo": demo, "targets": {
            "github": cfg["github"], "jira": cfg["jira"],
            "slack": {"workspace": cfg["slack"]["workspace"], "channels": cfg["slack"]["channels"]}}},
        "connected": scopes,
        "catalog": scopes,
        "indexed_repos": indexed,
        "neo4j": neo4j,
        "integrations": integrations,
        "providers": providers,
        "names": config.names(ws),
    }


@router.put("/api/w/{ws}/workspace")
def put_workspace(ws: str, body: dict = Body(...)):
    stored = _workspace(ws)
    merged = dict(stored)
    if "name" in body:
        merged["name"] = body["name"] if isinstance(body["name"], str) else ""
    for section in ("github", "jira", "slack"):
        if section not in body:
            continue
        if not isinstance(body[section], dict):
            raise HTTPException(422, f"{section} must be an object")
        update = dict(body[section])
        if section == "slack":  # learned from Slack by sync, never client-supplied
            update.pop("channel_names", None)
            update.pop("users", None)
        merged[section] = {**stored[section], **update}
    try:
        return config.save_workspace(ws, merged)
    except ValueError as error:
        raise HTTPException(422, str(error)) from None


@router.put("/api/w/{ws}/secrets")
def put_secrets(ws: str, body: dict = Body(...)):
    _workspace(ws)
    try:
        config.set_secrets(ws, body)
    except ValueError as error:  # messages name only the key, never a value
        raise HTTPException(422, str(error)) from None
    return config.secret_status(ws)


# ---------------------------------------------------------------- integration test + discovery
def _test(ws: str, cfg: dict, which: str) -> dict:
    from ..agent import llm

    if which == "llm":
        llm.set_workspace(ws)
        try:
            provider = config.get_secret(ws, "llm_provider") or next(
                (p["name"] for p in llm.providers(ws) if p["configured"]), None)
            if not provider:
                return {"ok": False, "detail": "No LLM key saved"}
            if provider not in llm.PROVIDERS:
                return {"ok": False, "detail": "Unknown LLM provider"}
            llm.ping(provider)
            return {"ok": True, "detail": "Model replied", "account": f"{provider} ({llm.model_for(provider)})"}
        finally:
            llm.set_workspace(None)
    client = _client(ws, cfg, which)
    if which == "github":
        account = client.whoami()
    elif which == "jira":
        me = client.myself()
        account = me.get("emailAddress") or me["displayName"]
    else:
        info = client.auth_test()
        account = f"{info['user']} @ {info['team']}".strip(" @")
    return {"ok": True, "detail": "Demo data" if cfg["demo"] else "Connected", "account": account}


@router.post("/api/w/{ws}/integrations/{which}/test")
def test_integration(ws: str, which: Integration):
    cfg = _workspace(ws)
    try:
        return _test(ws, cfg, which)
    except _Missing as error:
        return {"ok": False, "detail": str(error)}
    except RuntimeError as error:
        # llm.ping raises only fixed safe messages; source clients' errors are mapped by _safe
        return {"ok": False, "detail": str(error) if which == "llm" else _safe(LABEL[which], error)}
    except Exception as error:
        return {"ok": False, "detail": "Network error" if which == "llm" else _safe(LABEL[which], error)}


@router.get("/api/w/{ws}/integrations/{which}/resources")
def resources(ws: str, which: Literal["github", "jira", "slack"]):
    cfg = _workspace(ws)
    try:
        client = _client(ws, cfg, which)
    except _Missing as error:
        raise HTTPException(422, str(error)) from None
    try:
        if which == "github":
            items = [{"id": r["full_name"], "name": r["full_name"], "private": r["private"]}
                     for r in client.list_repos(cfg["github"]["owner"] or None)]
        elif which == "jira":
            items = [{"id": p["key"], "name": p["name"]} for p in client.projects()]
        else:
            items = [{"id": c["id"], "name": "#" + c["name"], "private": c["is_private"],
                      "detail": "bot is a member" if c["is_member"] else "bot not invited"} for c in client.channels()]
    except Exception as error:
        raise HTTPException(502, f"{LABEL[which]} discovery failed: {_safe(LABEL[which], error)}") from None
    return {"resources": items}
