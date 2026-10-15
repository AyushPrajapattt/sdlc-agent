"""Demo workspace: fake HTTP transports that serve data.py through the REAL clients, adapters and mappers."""

from __future__ import annotations

import json
import re
from urllib.parse import parse_qs, urlencode, urlsplit

from ..sources.github import client as gh_client
from ..sources.jira import client as jira_client
from ..sources.slack import client as slack_client
from . import data as d

DEMO_WORKSPACE = {
    "github": {"owner": d.OWNER, "repos": [d.REPO]},
    "jira": {"site": d.JIRA_SITE, "projects": ["PAY", "SEC"]},
    "slack": {"workspace": d.SLACK_WS, "channels": list(d.SLACK_THREADS)},
}


def _json(response_cls, payload, headers=None, status=200):
    return response_cls(status, headers or {}, json.dumps(payload).encode())


class GitHubDemoTransport:
    """Serves /repos/{owner}/{repo}/... with real Link-header pagination."""

    def get(self, url, headers, timeout):
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        path = parts.path.removeprefix(f"/repos/{d.OWNER}/{d.REPO}")
        m = re.fullmatch(r"/(?:pulls|issues)/(\d+)/(commits|reviews|comments)", path)
        if path == "/commits":
            items = d.COMMITS
        elif path == "/pulls":
            items = d.PULLS
        elif m and path.startswith("/pulls") and m.group(2) == "commits":
            items = d.PR_COMMITS.get(int(m.group(1)), [])
        elif m and path.startswith("/pulls") and m.group(2) == "reviews":
            items = d.PR_REVIEWS.get(int(m.group(1)), [])
        elif m and path.startswith("/pulls"):
            items = d.PR_REVIEW_COMMENTS.get(int(m.group(1)), [])
        elif m and path.startswith("/issues"):
            items = d.PR_ISSUE_COMMENTS.get(int(m.group(1)), [])
        else:
            return _json(gh_client.HTTPResponse, {"message": "Not Found"}, status=404)
        size, page = int(q.get("per_page", 30)), int(q.get("page", 1))
        chunk = items[(page - 1) * size: page * size]
        link = {}
        if page * size < len(items):
            link = {"Link": f'<{parts.scheme}://{parts.netloc}{parts.path}?{urlencode({**q, "page": page + 1})}>; rel="next"'}
        return _json(gh_client.HTTPResponse, chunk, link)


class JiraDemoTransport:
    def get(self, url, headers, timeout):
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        if parts.path.endswith("/search/jql"):
            project = re.search(r'project = "(\w+)"', q.get("jql", "")).group(1)
            issues = d.JIRA_ISSUES.get(project, [])
            start = int(q.get("nextPageToken", 0))
            size = int(q.get("maxResults", 50))
            body = {"issues": issues[start:start + size]}
            if start + size < len(issues):
                body["nextPageToken"] = str(start + size)
            else:
                body["isLast"] = True
            return _json(jira_client.HTTPResponse, body)
        m = re.search(r"/issue/([A-Z]+-\d+)/comment$", parts.path)
        if m:
            comments = d.JIRA_COMMENTS.get(m.group(1), [])
            start, size = int(q.get("startAt", 0)), int(q.get("maxResults", 50))
            return _json(jira_client.HTTPResponse, {
                "startAt": start, "maxResults": size, "total": len(comments), "comments": comments[start:start + size]})
        return _json(jira_client.HTTPResponse, {}, status=404)


class SlackDemoTransport:
    def get(self, url, headers, timeout):
        parts = urlsplit(url)
        q = {k: v[0] for k, v in parse_qs(parts.query).items()}
        threads = d.SLACK_THREADS.get(q.get("channel", ""), {})
        if parts.path.endswith("conversations.history"):
            roots = sorted((msgs[0] for msgs in threads.values()), key=lambda m: m["ts"], reverse=True)
            roots = [{k: v for k, v in m.items() if k != "thread_ts" or m.get("reply_count")} for m in roots]
            messages = roots
        elif parts.path.endswith("conversations.replies"):
            messages = threads.get(q.get("ts", ""), [])
        else:
            return _json(slack_client.HTTPResponse, {"ok": False, "error": "unknown_method"})
        start, size = int(q.get("cursor") or 0), int(q.get("limit", 15))
        body = {"ok": True, "messages": messages[start:start + size], "has_more": start + size < len(messages)}
        if body["has_more"]:
            body["response_metadata"] = {"next_cursor": str(start + size)}
        return _json(slack_client.HTTPResponse, body)


def demo_clients():
    """(GitHubClient, JiraClient, SlackClient) wired to the demo transports; no credentials, no network."""
    return (
        gh_client.GitHubClient(transport=GitHubDemoTransport()),
        jira_client.JiraClient(d.JIRA_SITE, transport=JiraDemoTransport()),
        slack_client.SlackClient(transport=SlackDemoTransport()),
    )
