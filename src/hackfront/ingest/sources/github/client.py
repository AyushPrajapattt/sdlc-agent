"""Small, dependency-free GitHub REST client with safe, opaque page cursors."""

from __future__ import annotations

import json
import os
import re
from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_VERSION = "2026-03-10"
DEFAULT_API_URL = "https://api.github.com"
MAX_PAGE_SIZE = 100
_DISCOVERY_PATH = r"/user|/user/repos|/(?:orgs|users)/[A-Za-z0-9-]+/repos"  # token test + repo picker only


class GitHubAPIError(RuntimeError):
    """Sanitized provider or transport failure; response bodies and credentials are omitted."""

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


class _SameOriginRedirect(HTTPRedirectHandler):
    def __init__(self, origin: tuple[str, str, int | None]):
        super().__init__()
        self._origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _origin(newurl) != self._origin:
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def _origin(url: str) -> tuple[str, str, int | None]:
    parsed = urlsplit(url)
    return parsed.scheme.lower(), (parsed.hostname or "").lower(), parsed.port


class UrlLibTransport:
    """HTTPS GET transport; redirects are restricted to the API origin."""

    def __init__(self, api_url: str = DEFAULT_API_URL):
        self._origin = _origin(api_url)

    def get(self, url: str, headers: Mapping[str, str], timeout: float) -> HTTPResponse:
        request = Request(url, headers=dict(headers), method="GET")
        opener = build_opener(_SameOriginRedirect(self._origin))
        try:
            with opener.open(request, timeout=timeout) as response:
                return HTTPResponse(response.status, dict(response.headers.items()), response.read())
        except HTTPError as error:
            error.close()
            raise GitHubAPIError(f"GitHub API returned HTTP {error.code}", error.code) from None
        except URLError as error:
            raise GitHubAPIError(f"GitHub API transport failed: {error.reason}") from None
        except TimeoutError:
            raise GitHubAPIError("GitHub API request timed out") from None


@dataclass(frozen=True, slots=True)
class Page:
    items: tuple[Mapping[str, object], ...]
    next_cursor: str | None


def _next_link(headers: Mapping[str, str]) -> str | None:
    link = next((value for key, value in headers.items() if key.lower() == "link"), "")
    for part in link.split(","):
        match = re.search(r"<([^>]+)>\s*;\s*rel=\"?next\"?", part.strip())
        if match:
            return match.group(1)
    return None


class GitHubClient:
    """GitHub REST access; tokens are sent only in the Authorization header."""

    def __init__(
        self,
        token: str | None = None,
        *,
        api_url: str = DEFAULT_API_URL,
        transport: Transport | None = None,
        timeout: float = 30.0,
    ):
        base = api_url.rstrip("/")
        parsed = urlsplit(base)
        if parsed.scheme != "https" or not parsed.netloc:
            raise ValueError("api_url must be an absolute HTTPS URL")
        self.api_url = base
        self._api_origin = _origin(base)
        self._api_path = parsed.path.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._transport = transport or UrlLibTransport(base)

    @classmethod
    def from_environment(cls, **kwargs) -> "GitHubClient":
        """Read optional credentials without placing them in URLs or logs."""
        return cls(token=os.environ.get("GITHUB_TOKEN"), **kwargs)

    def _validate_api_url(self, url: str) -> str:
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or _origin(url) != self._api_origin
            or not (
                parsed.path.startswith(f"{self._api_path}/repos/")
                or re.fullmatch(_DISCOVERY_PATH, parsed.path.removeprefix(self._api_path))
            )
        ):
            raise ValueError("GitHub API URL must stay under this host's /repos/ path")
        return url

    def whoami(self) -> str:
        """Login of the token's user (credential test)."""
        login = self.get_resource(f"{self.api_url}/user").get("login")
        if not isinstance(login, str):
            raise GitHubAPIError("expected a GitHub login")
        return login

    def list_repos(self, owner: str | None) -> list[dict]:
        """[{full_name, private}] of an owner's repos (org, else user) or the token's repos; 5 pages max."""
        if owner is None:
            return self._repos("user/repos", {"affiliation": "owner,collaborator,organization_member"})
        if not re.fullmatch(r"[A-Za-z0-9-]+", owner):
            raise ValueError("invalid owner")
        try:
            return self._repos(f"orgs/{owner}/repos")
        except GitHubAPIError as error:
            if error.status != 404:
                raise
            return self._repos(f"users/{owner}/repos")

    def _repos(self, path: str, params: Mapping[str, str] | None = None) -> list[dict]:
        out, cursor = [], None
        for _ in range(5):
            page = (self.get_page(path, cursor=cursor) if cursor
                    else self.get_page(path, params={"sort": "pushed", **(params or {})}))
            out += [{"full_name": r["full_name"], "private": bool(r.get("private"))}
                    for r in page.items if isinstance(r.get("full_name"), str)]
            cursor = page.next_cursor
            if not cursor:
                break
        return out

    def _headers(self) -> dict[str, str]:
        headers = {
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": API_VERSION,
            "User-Agent": "hackfront/0.1",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _get_json(self, url: str) -> tuple[object, Mapping[str, str]]:
        response = self._transport.get(self._validate_api_url(url), self._headers(), self._timeout)
        if response.status < 200 or response.status >= 300:
            raise GitHubAPIError(f"GitHub API returned HTTP {response.status}", response.status)
        try:
            return json.loads(response.body), response.headers
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GitHubAPIError("GitHub API returned invalid JSON", response.status) from None

    def get_page(
        self,
        path: str,
        *,
        cursor: str | None = None,
        per_page: int = MAX_PAGE_SIZE,
        params: Mapping[str, str] | None = None,
    ) -> Page:
        if not 1 <= per_page <= MAX_PAGE_SIZE:
            raise ValueError(f"per_page must be between 1 and {MAX_PAGE_SIZE}")
        if cursor and params:
            raise ValueError("do not combine a saved page cursor with new query parameters")
        if cursor:
            url = self._validate_api_url(cursor)
        else:
            endpoint = urljoin(f"{self.api_url}/", path.lstrip("/"))
            query = {"per_page": str(per_page), **(params or {})}
            parts = urlsplit(endpoint)
            url = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), ""))
        payload, headers = self._get_json(url)
        if not isinstance(payload, list) or any(not isinstance(item, dict) for item in payload):
            raise GitHubAPIError("expected a JSON array from paginated endpoint")
        return Page(tuple(payload), _next_link(headers))

    def get_resource(self, url: str) -> Mapping[str, object]:
        payload, _ = self._get_json(url)
        if not isinstance(payload, dict):
            raise GitHubAPIError("expected a JSON object from resource endpoint")
        return payload

    @staticmethod
    def repository_path(owner: str, repository: str, resource: str) -> str:
        for value, name in ((owner, "owner"), (repository, "repository")):
            if not value or "/" in value or "?" in value or "#" in value:
                raise ValueError(f"invalid {name}")
        segments = resource.strip("/").split("/")
        if not segments or any(segment in {"", ".", ".."} or "?" in segment or "#" in segment for segment in segments):
            raise ValueError("invalid resource path")
        return f"repos/{owner}/{repository}/{'/'.join(segments)}"
