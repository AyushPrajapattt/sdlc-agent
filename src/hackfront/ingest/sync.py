"""Workspace sync: GitHub / Jira / Slack (live or demo clients) -> text references -> Neo4j.

Every sync is a bounded full backfill through the idempotent writer, so re-running it never duplicates
nodes or edges. # ponytail: no persisted incremental cursor yet; add `since` per stream when volume needs it.
"""

from __future__ import annotations

from .. import config
from .core import run_ingestion
from .extraction.links import LinkConfig, add_text_references
from .sources.github.adapter import GitHubAdapter
from .sources.github.mapper import ADAPTER_VERSION as GH_VERSION
from .sources.github.client import GitHubClient
from .sources.jira.adapter import JiraAdapter
from .sources.jira.client import JiraClient
from .sources.jira.mapper import ADAPTER_VERSION as JIRA_VERSION
from .sources.slack.adapter import SlackAdapter
from .sources.slack.client import SlackClient
from .sources.slack.mapper import ADAPTER_VERSION as SLACK_VERSION
from .storage.neo4j import Neo4jStore

MAX_PAGES = 20


class _LinkingWriter:
    """Adds explicit text references to each artifact just before it is stored."""

    def __init__(self, store: Neo4jStore, links: LinkConfig):
        self.store, self.links = store, links

    def write_artifact(self, artifact):
        return self.store.write_artifact(add_text_references(artifact, self.links))


def _stream(label, fetch, writer, version, tap=None) -> dict:
    def fetch_page(cursor):
        page = fetch(cursor)
        if tap:
            tap(page.items)
        return page

    return run_ingestion(source=label, fetch_page=fetch_page, writer=writer, max_pages=MAX_PAGES,
                         adapter_version=version).summary.to_dict()


def _merge(label: str, parts: list[dict], version: str) -> dict:
    """Fold per-parent runs (one per PR/issue/thread) into one summary line."""
    counts = {k: sum(p["counts"][k] for p in parts) for k in ("pages_fetched", "fetched", "normalized", "persisted")}
    return {"source": label, "counts": counts, "complete": all(p["complete"] for p in parts),
            "errors": [e for p in parts for e in p["errors"]], "versions": {"adapter": version}}


def _brief(summary: dict) -> dict:
    return {"stream": summary["source"], "counts": summary["counts"], "complete": summary["complete"],
            "errors": summary["errors"]}


def _github(client, owner, repo, writer) -> list[dict]:
    adapter, prs, out = GitHubAdapter(client), [], []
    out.append(_stream(f"github:{owner}/{repo}:commits", lambda c: adapter.commits_page(owner, repo, cursor=c),
                       writer, GH_VERSION))
    out.append(_stream(f"github:{owner}/{repo}:pulls", lambda c: adapter.pull_requests_page(owner, repo, cursor=c),
                       writer, GH_VERSION, tap=lambda items: prs.extend(int(a.source.source_id) for a in items)))
    activity = [
        _stream(f"github:{owner}/{repo}:pr_activity",
                lambda c, n=n, kind=kind: adapter.pull_request_activity_page(owner, repo, n, kind, cursor=c),
                writer, GH_VERSION)
        for n in prs for kind in ("issue_comments", "reviews", "review_comments")
    ]
    if activity:
        out.append(_merge(f"github:{owner}/{repo}:pr_activity", activity, GH_VERSION))
    return out


def _jira(client, site, project, writer) -> list[dict]:
    adapter, keys = JiraAdapter(client, site), []
    out = [_stream(f"jira:{project}:issues", lambda c: adapter.issues_page(project, cursor=c), writer, JIRA_VERSION,
                   tap=lambda items: keys.extend(a.source.source_id for a in items))]
    comments = [_stream(f"jira:{project}:comments", lambda c, k=k: adapter.comments_page(k, cursor=c), writer, JIRA_VERSION)
                for k in keys]
    if comments:
        out.append(_merge(f"jira:{project}:comments", comments, JIRA_VERSION))
    return out


def _slack(client, workspace, channel, writer) -> list[dict]:
    adapter, threads = SlackAdapter(client), []
    out = [_stream(f"slack:{channel}:history", lambda c: adapter.history_page(workspace, channel, cursor=c), writer,
                   SLACK_VERSION,
                   tap=lambda items: threads.extend(a.source.source_id for a in items if a.context.get("reply_count")))]
    replies = [_stream(f"slack:{channel}:replies",
                       lambda c, ts=ts: adapter.thread_page(workspace, channel, ts, cursor=c), writer, SLACK_VERSION)
               for ts in threads]
    if replies:
        out.append(_merge(f"slack:{channel}:replies", replies, SLACK_VERSION))
    return out


def sync_workspace(workspace: dict, *, demo: bool = False) -> list[dict]:
    """Ingest every configured source; returns one safe summary per stream (no secrets, no content)."""
    ws = config.validate_workspace(workspace)
    gh, jira, slack = ws["github"], ws["jira"], ws["slack"]
    if not (gh["repos"] or jira["projects"] or slack["channels"]):
        raise RuntimeError("workspace has no sources configured")
    if demo:
        from .demo import demo_clients

        gh_client, jira_client, slack_client = demo_clients()
    else:
        gh_client = GitHubClient.from_environment()
        jira_client = JiraClient.from_environment(base_url=jira["site"]) if jira["site"] else None
        slack_client = SlackClient.from_environment()
    if jira["projects"] and jira_client is None:
        raise RuntimeError("jira.site is required to sync Jira projects")
    if gh["repos"] and not gh["owner"]:
        raise RuntimeError("github.owner is required to sync GitHub repositories")
    if slack["channels"] and not slack["workspace"]:
        raise RuntimeError("slack.workspace is required to sync Slack channels")

    with Neo4jStore.from_environment() as store:
        store.initialize_schema()
        writer = _LinkingWriter(store, LinkConfig.from_workspace(ws))
        out: list[dict] = []
        for repo in gh["repos"]:
            out += _github(gh_client, gh["owner"], repo, writer)
        for project in jira["projects"]:
            out += _jira(jira_client, jira["site"], project, writer)
        for channel in slack["channels"]:
            out += _slack(slack_client, slack["workspace"], channel, writer)
    return [_brief(s) for s in out]


def graph_counts() -> dict:
    driver = config.neo4j_driver()
    try:
        db = config.neo4j_database()

        def rows(query):
            records, _, _ = driver.execute_query(query, database_=db, routing_="r")
            return records

        totals = rows("MATCH (a:Artifact) RETURN count(a) AS n, count(CASE WHEN a.is_stub THEN 1 END) AS stubs")[0]
        edges = rows("MATCH (:Artifact)-[r]->(:Artifact) RETURN count(r) AS n")[0]["n"]
        by_kind = {r["k"]: r["n"] for r in rows(
            "MATCH (a:Artifact) WHERE NOT coalesce(a.is_stub, false) RETURN a.record_kind AS k, count(*) AS n")}
        by_provider = {r["p"]: r["n"] for r in rows(
            "MATCH (a:Artifact) WHERE NOT coalesce(a.is_stub, false) RETURN a.provider AS p, count(*) AS n")}
        return {"artifacts": totals["n"] - totals["stubs"], "stubs": totals["stubs"], "edges": edges,
                "by_kind": by_kind, "by_provider": by_provider}
    finally:
        driver.close()
