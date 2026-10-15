"""Small Jira Cloud REST client with injectable transport and bounded pages."""

from __future__ import annotations

import base64
import json
import os
import re
from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


MAX_PAGE_SIZE = 100
ISSUE_FIELDS = "summary,description,issuetype,project,status,priority,reporter,created,updated,labels,issuelinks"
PROJECT_KEY = re.compile(r"[A-Z][A-Z0-9_]{1,9}")


class JiraAPIError(RuntimeError):
    def __init__(self, message: str, status: int | None = None):
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class HTTPResponse:
    status: int
    headers: Mapping[str, str]
    body: bytes


class Transport(Protocol):
    def get(self, url: str, headers: Mapping[str, str], timeout: float) -> HTTPResponse: ...


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


class _SameOriginRedirect(HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int | None]):
        super().__init__()
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(newurl) != self.origin:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrlLibTransport:
    def __init__(self, base_url: str):
        self.origin = _origin(base_url)

    def get(self, url: str, headers: Mapping[str, str], timeout: float) -> HTTPResponse:
        try:
            with build_opener(_SameOriginRedirect(self.origin)).open(
                Request(url, headers=dict(headers), method="GET"), timeout=timeout
            ) as response:
                return HTTPResponse(response.status, dict(response.headers.items()), response.read())
        except HTTPError as error:
            error.close()
            raise JiraAPIError(f"Jira API returned HTTP {error.code}", error.code) from None
        except URLError as error:
            raise JiraAPIError("Jira API transport failed") from None
        except TimeoutError:
            raise JiraAPIError("Jira API request timed out") from None


@dataclass(frozen=True, slots=True)
class Page:
    items: tuple[Mapping[str, object], ...]
    next_cursor: str | None


class JiraClient:
    def __init__(
        self,
        base_url: str,
        token: str | None = None,
        *,
        email: str | None = None,
        transport: Transport | None = None,
        timeout: float = 30.0,
    ):
        parsed = urlsplit(base_url.rstrip("/"))
        if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password or parsed.query or parsed.fragment:
            raise ValueError("base_url must be an absolute HTTPS URL")
        self.base_url = base_url.rstrip("/")
        self.origin = _origin(self.base_url)
        self.base_path = parsed.path.rstrip("/")
        self.token = token
        self.email = email
        self.timeout = timeout
        self.transport = transport or UrlLibTransport(self.base_url)

    @classmethod
    def from_environment(cls, *, base_url: str, **kwargs) -> "JiraClient":
        return cls(
            base_url,
            os.environ.get("JIRA_API_TOKEN"),
            email=os.environ.get("JIRA_EMAIL"),
            **kwargs,
        )

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": "application/json", "User-Agent": "hackfront/0.1"}
        if self.token:
            value = f"{self.email}:{self.token}" if self.email else self.token
            scheme = "Basic " + base64.b64encode(value.encode()).decode() if self.email else "Bearer " + value
            headers["Authorization"] = scheme
        return headers

    def _validate_url(self, url: str) -> str:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or parsed.username
            or parsed.password
            or _origin(url) != self.origin
            or not parsed.path.startswith(f"{self.base_path}/rest/api/")
        ):
            raise ValueError("Jira URL must stay under this host's REST API")
        return url

    def _get_json(self, url: str) -> object:
        response = self.transport.get(self._validate_url(url), self._headers(), self.timeout)
        if not 200 <= response.status < 300:
            raise JiraAPIError(f"Jira API returned HTTP {response.status}", response.status)
        try:
            return json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise JiraAPIError("Jira API returned invalid JSON", response.status) from None

    def myself(self) -> dict:
        """{displayName, emailAddress?} of the credential's user (credential test)."""
        payload = self._get_json(f"{self.base_url}/rest/api/3/myself")
        if not isinstance(payload, dict) or not isinstance(payload.get("displayName"), str):
            raise JiraAPIError("expected a Jira user")
        out = {"displayName": payload["displayName"]}
        if isinstance(payload.get("emailAddress"), str):
            out["emailAddress"] = payload["emailAddress"]
        return out

    def projects(self) -> list[dict]:
        """[{key, name}] visible to the credential; 5 pages of 100 at most."""
        out, start = [], 0
        for _ in range(5):
            payload = self._get_json(f"{self.base_url}/rest/api/3/project/search?"
                                     + urlencode({"startAt": start, "maxResults": MAX_PAGE_SIZE}))
            values = payload.get("values") if isinstance(payload, dict) else None
            if not isinstance(values, list):
                raise JiraAPIError("expected Jira projects")
            out += [{"key": p["key"], "name": str(p.get("name") or p["key"])}
                    for p in values if isinstance(p, dict) and isinstance(p.get("key"), str)]
            if payload.get("isLast") is not False or not values:
                break
            start += len(values)
        return out

    def get_issue(self, issue_key: str) -> Mapping[str, object]:
        if not issue_key or any(char in issue_key for char in "/?#"):
            raise ValueError("invalid issue key")
        url = f"{self.base_url}/rest/api/3/issue/{issue_key}?{urlencode({'fields': ISSUE_FIELDS})}"
        payload = self._get_json(url)
        if not isinstance(payload, dict):
            raise JiraAPIError("expected a JSON object for Jira issue")
        return payload

    def issues_page(self, project: str, *, cursor: str | None = None, per_page: int = 100) -> Page:
        """One page of a project's issues via the enhanced JQL search (nextPageToken pagination)."""
        if not PROJECT_KEY.fullmatch(project):
            raise ValueError("invalid project key")
        if not 1 <= per_page <= MAX_PAGE_SIZE:
            raise ValueError(f"per_page must be between 1 and {MAX_PAGE_SIZE}")
        if cursor:
            url = self._validate_url(cursor)
        else:
            query = urlencode({"jql": f'project = "{project}" ORDER BY updated DESC',
                               "fields": ISSUE_FIELDS, "maxResults": per_page})
            url = f"{self.base_url}/rest/api/3/search/jql?{query}"
        payload = self._get_json(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("issues"), list):
            raise JiraAPIError("expected Jira search results")
        issues = payload["issues"]
        if any(not isinstance(item, dict) for item in issues):
            raise JiraAPIError("expected Jira issue objects")
        token = payload.get("nextPageToken")
        next_cursor = None
        if isinstance(token, str) and token and payload.get("isLast") is not True:
            base = url.split("&nextPageToken=")[0]
            next_cursor = f"{base}&{urlencode({'nextPageToken': token})}"
        return Page(tuple(issues), next_cursor)

    def comments_page(self, issue_key: str, *, cursor: str | None = None, per_page: int = 100) -> Page:
        if not issue_key or any(char in issue_key for char in "/?#"):
            raise ValueError("invalid issue key")
        if not 1 <= per_page <= MAX_PAGE_SIZE:
            raise ValueError(f"per_page must be between 1 and {MAX_PAGE_SIZE}")
        if cursor:
            url = self._validate_url(cursor)
        else:
            query = urlencode({"startAt": 0, "maxResults": per_page})
            url = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment?{query}"
        payload = self._get_json(url)
        if not isinstance(payload, dict) or not isinstance(payload.get("comments"), list):
            raise JiraAPIError("expected paginated Jira comments")
        comments = payload["comments"]
        if any(not isinstance(item, dict) for item in comments):
            raise JiraAPIError("expected Jira comment objects")
        start = payload.get("startAt", 0)
        total = payload.get("total", 0)
        next_cursor = None
        if isinstance(start, int) and isinstance(total, int) and start + len(comments) < total:
            if not comments:
                raise JiraAPIError("Jira returned an empty comment page before the end of the collection")
            query = urlencode({"startAt": start + len(comments), "maxResults": per_page})
            next_cursor = f"{self.base_url}/rest/api/3/issue/{issue_key}/comment?{query}"
        return Page(tuple(comments), next_cursor)
