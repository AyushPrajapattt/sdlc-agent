"""Per-workspace background sync: GitHub / Jira / Slack (live or demo clients) -> text references -> Neo4j.

Two ways to run the same job through the idempotent writer (re-running never duplicates nodes or edges):
  background  `start_sync` returns at once and a daemon thread keeps going (long-lived hosts: local, Render, Docker);
  inline      `run_sync_inline` does the work inside the request with a time budget (Vercel: functions only run while a
              request is open and are capped; the default there). Pick with HACKFRONT_SYNC=inline|background.
Progress is persisted (state.py) with a heartbeat, so ANY instance can report a running job and tell a dead one apart.
# ponytail: no persisted incremental cursor yet; an inline run that hits the time budget restarts from the newest page.
"""

from __future__ import annotations

import copy
import json
import os
import threading
import time
from datetime import datetime, timezone

from .. import config
from .. import state as app_state
from .core import run_ingestion
from .extraction.links import LinkConfig, add_text_references
from .sources.github.adapter import GitHubAdapter
from .sources.github.client import GitHubClient
from .sources.github.mapper import ADAPTER_VERSION as GH_VERSION
from .sources.jira.adapter import JiraAdapter
from .sources.jira.client import JiraClient
from .sources.jira.mapper import ADAPTER_VERSION as JIRA_VERSION
from .sources.slack.adapter import SlackAdapter
from .sources.slack.client import SlackClient
from .sources.slack.mapper import ADAPTER_VERSION as SLACK_VERSION
from .storage.neo4j import Neo4jStore

PAGES = {"standard": 20, "deep": 100}  # pages per stream
HEARTBEAT_SECONDS = 5
STALE_SECONDS = 30  # a persisted "running" job whose heartbeat is older than this has lost its process


class _OutOfTime(Exception):
    """Raised inside a page fetch when the inline time budget is spent."""


class _LinkingWriter:
    """Adds explicit text references to each artifact just before it is stored."""

    def __init__(self, store: Neo4jStore, links: LinkConfig):
        self.store, self.links = store, links

    def write_artifact(self, artifact):
        return self.store.write_artifact(add_text_references(artifact, self.links))


class _CountingWriter:
    def __init__(self, inner, on_write):
        self.inner, self.on_write = inner, on_write

    def write_artifact(self, artifact):
        out = self.inner.write_artifact(artifact)
        self.on_write()
        return out


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _idle() -> dict:
    return {"state": "idle", "mode": "standard", "streams": [], "totals": _totals([]), "complete": False}


def _totals(streams: list[dict]) -> dict:
    return {"fetched": sum(s["fetched"] for s in streams), "persisted": sum(s["persisted"] for s in streams),
            "errors": sum(len(s["errors"]) for s in streams)}


class _Job:
    def __init__(self, slug: str, mode: str, budget: float | None = None):
        self.slug, self.pages = slug, PAGES[mode]
        self.lock = threading.RLock()
        self.status = {"state": "running", "mode": mode, "started_at": _now(), "streams": [], "complete": False}
        self.by_name: dict[str, dict] = {}
        self._saved = 0.0
        self._dirty = False  # a throttled update waiting for the next flush
        self.deadline = time.monotonic() + budget if budget else None
        self.save(force=True)

    def snapshot(self) -> dict:
        with self.lock:
            out = copy.deepcopy(self.status)
        out["totals"] = _totals(out["streams"])
        return out

    def expired(self) -> bool:
        return self.deadline is not None and time.monotonic() > self.deadline

    def out_of_time(self, name: str) -> None:
        with self.lock:
            s = self.stream(name)
            if not any(e["type"] == "TimeBudget" for e in s["errors"]):
                s["errors"].append({"stage": "budget", "type": "TimeBudget",
                                    "message": "Stopped at the time limit; run the sync again to continue"})
            self.save()

    def keepalive(self) -> None:
        """While running: flush throttled updates within ~1 s and refresh the heartbeat every HEARTBEAT_SECONDS."""
        while True:
            time.sleep(1)
            with self.lock:
                if self.status["state"] != "running":
                    return
                if self._dirty or time.monotonic() - self._saved >= HEARTBEAT_SECONDS:
                    self.save(force=True)

    def save(self, force: bool = False) -> None:
        """Atomic write of sync.json, at most ~2/s unless forced."""
        with self.lock:
            if not force and time.monotonic() - self._saved < 0.5:
                self._dirty = True  # dropped, not lost: keepalive flushes it
                return
            self._saved = time.monotonic()
            self._dirty = False
            self.status["heartbeat"] = _now()
            try:
                app_state.backend().write_sync(self.slug, self.snapshot())
            except Exception:  # workspace deleted mid-run or state store briefly unavailable: live status still works
                pass

    def stream(self, name: str, status: str = "running") -> dict:
        with self.lock:
            s = self.by_name.get(name)
            if s is None:
                s = self.by_name[name] = {"stream": name, "status": status, "pages": 0, "fetched": 0,
                                          "persisted": 0, "errors": []}
                self.status["streams"].append(s)
                self.save()
            return s

    def bump(self, name: str, **inc: int) -> None:
        with self.lock:
            s = self.stream(name)
            for key, value in inc.items():
                s[key] += value
            self.save()

    def fail(self, name: str, message: str) -> None:
        with self.lock:
            s = self.stream(name, "failed")
            s["errors"].append({"stage": "config", "type": "NotConfigured", "message": message})
            self.save()

    def finish(self, name: str, complete: bool) -> None:
        with self.lock:
            s = self.stream(name)
            timed_out = any(e["type"] == "TimeBudget" for e in s["errors"])
            s["status"] = "done" if complete else "incomplete" if (s["persisted"] or not s["errors"] or timed_out) else "failed"
            self.save()

    def end(self, state: str | None = None, error: str | None = None, graph: dict | None = None) -> None:
        with self.lock:
            for s in self.status["streams"]:
                if s["status"] == "running":
                    s["status"] = "failed"
            streams = self.status["streams"]
            self.status["complete"] = bool(streams) and all(s["status"] == "done" for s in streams)
            self.status["state"] = state or ("failed" if streams and all(s["status"] == "failed" for s in streams) else "done")
            self.status["finished_at"] = _now()
            if error:
                self.status["error"] = error
            if graph:
                self.status["graph"] = graph
            self.save(force=True)


_jobs: dict[str, _Job] = {}
_registry = threading.Lock()


def _run(job: _Job, name: str, fetch, writer, version: str, tap=None) -> bool:
    """One paged run feeding the live stream `name`; returns whether the source was exhausted without errors."""
    job.stream(name)
    if job.expired():
        job.out_of_time(name)
        return False

    def fetch_page(cursor):
        if job.expired():
            raise _OutOfTime()
        page = fetch(cursor)
        if tap:
            tap(page.items)
        job.bump(name, pages=1, fetched=len(page.items))
        return page

    summary = run_ingestion(source=name, fetch_page=fetch_page, writer=_CountingWriter(writer, lambda: job.bump(name, persisted=1)),
                            max_pages=job.pages, adapter_version=version).summary.to_dict()
    with job.lock:
        errors = summary["errors"]
        if job.expired():  # the generic fetch error is really the time limit
            errors = [e for e in errors if e["type"] != "_OutOfTime"]
            job.out_of_time(name)
        job.stream(name)["errors"] += errors
    return summary["complete"]


def _stream(job, name, fetch, writer, version, tap=None) -> None:
    job.finish(name, _run(job, name, fetch, writer, version, tap))


def _each(job, name, parents, fetch_for, writer, version) -> None:
    """One aggregated stream over per-parent runs (PR / issue / thread), live after each parent."""
    if not parents:
        return
    job.stream(name)
    ok = True
    for parent in parents:
        if job.expired():
            job.out_of_time(name)
            ok = False
            break
        ok &= _run(job, name, fetch_for(parent), writer, version)
    job.finish(name, ok)


def _github(job, client, owner, repo, writer) -> None:
    adapter, prs = GitHubAdapter(client), []
    base = f"github:{owner}/{repo}"
    _stream(job, f"{base}:commits", lambda c: adapter.commits_page(owner, repo, cursor=c), writer, GH_VERSION)
    _stream(job, f"{base}:pulls", lambda c: adapter.pull_requests_page(owner, repo, cursor=c), writer, GH_VERSION,
            tap=lambda items: prs.extend(int(a.source.source_id) for a in items))
    _each(job, f"{base}:pr_activity", [(n, k) for n in prs for k in ("issue_comments", "reviews", "review_comments")],
          lambda p: lambda c: adapter.pull_request_activity_page(owner, repo, p[0], p[1], cursor=c), writer, GH_VERSION)


def _jira(job, client, site, project, writer) -> None:
    adapter, keys = JiraAdapter(client, site), []
    _stream(job, f"jira:{project}:issues", lambda c: adapter.issues_page(project, cursor=c), writer, JIRA_VERSION,
            tap=lambda items: keys.extend(a.source.source_id for a in items))
    _each(job, f"jira:{project}:comments", keys, lambda k: lambda c: adapter.comments_page(k, cursor=c), writer, JIRA_VERSION)


def _slack(job, client, workspace, channel, writer) -> None:
    adapter, threads = SlackAdapter(client), []
    _stream(job, f"slack:{channel}:history", lambda c: adapter.history_page(workspace, channel, cursor=c), writer,
            SLACK_VERSION, tap=lambda items: threads.extend(a.source.source_id for a in items if a.context.get("reply_count")))
    _each(job, f"slack:{channel}:replies", threads, lambda ts: lambda c: adapter.thread_page(workspace, channel, ts, cursor=c),
          writer, SLACK_VERSION)


def _clients(slug: str, ws: dict, job: _Job):
    """(github, jira, slack) clients; None when a source has no targets or lacks credentials/config (its targets are
    then recorded as failed streams with a safe message; secret values never appear)."""
    if ws["demo"]:
        from .demo import demo_clients

        return demo_clients()
    gh, jira, slack = ws["github"], ws["jira"], ws["slack"]
    get = lambda key: config.get_secret(slug, key)  # noqa: E731
    wanted = (  # (stream names, missing-setting messages)
        ([f"github:{r if '/' in r else gh['owner'] + '/' + r}" for r in gh["repos"]],
         ["GitHub token not saved"] * (not get("github_token"))
         + ["GitHub owner not set"] * (not gh["owner"] and any("/" not in r for r in gh["repos"]))),
        ([f"jira:{p}" for p in jira["projects"]],
         ["Jira site not set"] * (not jira["site"]) + ["Jira email not saved"] * (not get("jira_email"))
         + ["Jira token not saved"] * (not get("jira_token"))),
        ([f"slack:{c}" for c in slack["channels"]],
         ["Slack token not saved"] * (not get("slack_token")) + ["Slack workspace not set"] * (not slack["workspace"])),
    )
    ready = []
    for names, problems in wanted:
        for name in names if problems else []:
            job.fail(name, "; ".join(problems))
        ready.append(bool(names) and not problems)
    return (
        GitHubClient(token=get("github_token")) if ready[0] else None,
        JiraClient(jira["site"], get("jira_token"), email=get("jira_email")) if ready[1] else None,
        SlackClient(get("slack_token")) if ready[2] else None,
    )


def _learn_slack_names(slug: str, client: SlackClient, channels: list[str]) -> None:
    """Best effort (needs channels:read / users:read); failures are ignored. Keeps only configured channels' names."""
    try:
        users = client.users()
    except Exception:  # noqa: BLE001
        users = {}
    try:
        found = {c["id"]: c["name"] for c in client.channels() if c["id"] in channels}
    except Exception:  # noqa: BLE001
        found = {}
    if users or found:
        ws = config.load_workspace(slug)
        slack = ws["slack"]
        config.save_workspace(slug, {**ws, "slack": {**slack, "users": {**slack["users"], **users},
                                                     "channel_names": {**slack["channel_names"], **found}}})


def _execute(job: _Job, ws: dict) -> None:
    slug, gh, jira, slack = job.slug, ws["github"], ws["jira"], ws["slack"]
    threading.Thread(target=job.keepalive, daemon=True, name=f"sync-heartbeat-{slug}").start()
    try:
        gh_client, jira_client, slack_client = _clients(slug, ws, job)
        with Neo4jStore.from_environment() as store:
            store.initialize_schema()
            writer = _LinkingWriter(store, LinkConfig.from_workspace(ws))
            if gh_client:
                for repo in gh["repos"]:
                    owner, _, name = repo.rpartition("/")
                    _github(job, gh_client, owner or gh["owner"], name, writer)
            if jira_client:
                for project in jira["projects"]:
                    _jira(job, jira_client, jira["site"], project, writer)
            if slack_client:
                for channel in slack["channels"]:
                    _slack(job, slack_client, slack["workspace"], channel, writer)
                if not ws["demo"] and not job.expired():
                    _learn_slack_names(slug, slack_client, slack["channels"])
        try:
            scopes = config.scopes(slug)
            graph = scoped_counts([*scopes["repos"], *scopes["jira"], *scopes["slack"]])
        except Exception:  # noqa: BLE001 - counts are informational
            graph = None
        job.end(graph=graph)
    except Exception as error:  # noqa: BLE001 - status gets the exception type only (messages may carry URIs)
        job.end("failed", f"Sync failed ({type(error).__name__}); see server logs")


def sync_mode() -> str:
    """'inline' on Vercel (VERCEL is set there) unless HACKFRONT_SYNC says otherwise; 'background' everywhere else."""
    chosen = os.environ.get("HACKFRONT_SYNC", "").lower()
    return chosen if chosen in ("inline", "background") else "inline" if os.environ.get("VERCEL") else "background"


def _alive(status: dict) -> bool:
    """A persisted job is alive if its owner refreshed `heartbeat` recently (the owner may be another instance)."""
    try:
        beat = datetime.strptime(status["heartbeat"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (KeyError, TypeError, ValueError):
        return False
    return (datetime.now(timezone.utc) - beat).total_seconds() < STALE_SECONDS


def _prepare(slug: str, mode: str, budget: float | None = None) -> tuple[_Job, dict]:
    """Validate and register a job. Raises LookupError (unknown workspace), ValueError (bad mode / no sources),
    RuntimeError (already running here, or in another instance with a live heartbeat)."""
    if mode not in PAGES:
        raise ValueError("mode must be standard or deep")
    ws = config.load_workspace(slug)
    if not (ws["github"]["repos"] or ws["jira"]["projects"] or ws["slack"]["channels"]):
        raise ValueError("no sources configured")
    with _registry:
        current = _jobs.get(slug)
        if current and current.status["state"] == "running":
            raise RuntimeError("a sync is already running")
        try:
            persisted = app_state.backend().read_sync(slug)
        except Exception:  # noqa: BLE001  (state store briefly unavailable: do not block starting)
            persisted = None
        if persisted and persisted.get("state") == "running" and _alive(persisted):
            raise RuntimeError("a sync is already running")
        job = _jobs[slug] = _Job(slug, mode, budget)
    return job, ws


def start_sync(slug: str, mode: str = "standard") -> dict:
    """Start the job in a daemon thread and return its initial status (long-lived hosts)."""
    job, ws = _prepare(slug, mode)
    threading.Thread(target=_execute, args=(job, ws), daemon=True, name=f"sync-{slug}").start()
    return job.snapshot()


def run_sync_inline(slug: str, mode: str = "standard", budget: float | None = None) -> dict:
    """Run the job in the calling thread and return the FINAL status (serverless hosts). Stops cleanly after `budget`
    seconds (default HACKFRONT_SYNC_BUDGET, 240: below Vercel Hobby's 300 s cap); unfinished streams are `incomplete`."""
    budget = budget if budget is not None else float(os.environ.get("HACKFRONT_SYNC_BUDGET", "240"))
    job, ws = _prepare(slug, mode, budget)
    _execute(job, ws)
    return job.snapshot()


def sync_status(slug: str) -> dict:
    """Live status if this process runs the job, else the persisted one (possibly owned by another instance), else idle."""
    job = _jobs.get(config.check_slug(slug))
    if job:
        return job.snapshot()
    try:
        status = app_state.backend().read_sync(slug)
    except Exception:  # state store unavailable: report idle rather than fail the poll
        return _idle()
    if not isinstance(status, dict) or not isinstance(status.get("streams"), list):
        return _idle()
    if status.get("state") == "running" and not _alive(status):  # its owner stopped refreshing the heartbeat
        status = {**status, "state": "failed", "error": "interrupted", "complete": False}
        for s in status["streams"]:
            if s.get("status") == "running":
                s["status"] = "failed"
    status["totals"] = _totals(status["streams"])
    return status


def scoped_counts(scopes: list[str]) -> dict:
    """Graph size limited to a workspace's scopes; stubs = placeholder nodes its artifacts point at."""
    driver = config.neo4j_driver()
    try:
        def one(query):
            records, _, _ = driver.execute_query(query, scopes=scopes, database_=config.neo4j_database(), routing_="r")
            return records[0]["n"]

        return {
            "artifacts": one("MATCH (a:Artifact) WHERE a.scope IN $scopes AND NOT coalesce(a.is_stub, false) RETURN count(a) AS n"),
            "edges": one("MATCH (a:Artifact)-[r]->(:Artifact) WHERE a.scope IN $scopes RETURN count(r) AS n"),
            "stubs": one("MATCH (a:Artifact)-->(s:Artifact) WHERE a.scope IN $scopes AND s.is_stub RETURN count(DISTINCT s) AS n"),
        }
    finally:
        driver.close()


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
