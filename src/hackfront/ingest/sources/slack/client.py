"""Slack conversations.replies client with injectable transport and page cursors."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Mapping, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener


API_BASE = "https://slack.com/api"
MAX_PAGE_SIZE = 15


class SlackAPIError(RuntimeError):
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


class _SlackRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        old, new = urlsplit(req.full_url), urlsplit(newurl)
        if (new.scheme, new.hostname, new.port) != (old.scheme, old.hostname, old.port):
            return None
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class UrlLibTransport:
    def get(self, url: str, headers: Mapping[str, str], timeout: float) -> HTTPResponse:
        try:
            with build_opener(_SlackRedirect()).open(
                Request(url, headers=dict(headers), method="GET"), timeout=timeout
            ) as response:
                return HTTPResponse(response.status, dict(response.headers.items()), response.read())
        except HTTPError as error:
            error.close()
            raise SlackAPIError(f"Slack API returned HTTP {error.code}", error.code) from None
        except URLError:
            raise SlackAPIError("Slack API transport failed") from None
        except TimeoutError:
            raise SlackAPIError("Slack API request timed out") from None


@dataclass(frozen=True, slots=True)
class Page:
    items: tuple[Mapping[str, object], ...]
    next_cursor: str | None


class SlackClient:
    def __init__(self, token: str | None = None, *, transport: Transport | None = None, timeout: float = 30.0):
        self.token = token
        self.transport = transport or UrlLibTransport()
        self.timeout = timeout

    @classmethod
    def from_environment(cls, **kwargs) -> "SlackClient":
        return cls(os.environ.get("SLACK_BOT_TOKEN"), **kwargs)

    def _call(self, method: str, params: dict) -> Page:
        payload = self._request(method, params)
        messages = payload.get("messages")
        metadata = payload.get("response_metadata")
        if not isinstance(messages, list) or any(not isinstance(item, dict) for item in messages):
            raise SlackAPIError("expected Slack message objects")
        next_cursor = metadata.get("next_cursor") if isinstance(metadata, dict) else None
        if payload.get("has_more") is True and not next_cursor:
            raise SlackAPIError("Slack indicated more messages without returning a cursor")
        return Page(tuple(messages), next_cursor if isinstance(next_cursor, str) and next_cursor else None)

    def auth_test(self) -> dict:
        """{user, team} of the token (credential test)."""
        payload = self._request("auth.test", {})
        return {"user": str(payload.get("user") or ""), "team": str(payload.get("team") or "")}

    def _list(self, method: str, field: str, params: dict) -> list[dict]:
        out, cursor = [], ""
        for _ in range(5):
            payload = self._request(method, {**params, **({"cursor": cursor} if cursor else {})})
            items = payload.get(field)
            if not isinstance(items, list):
                raise SlackAPIError(f"expected Slack {field}")
            out += [i for i in items if isinstance(i, dict)]
            meta = payload.get("response_metadata")
            cursor = meta.get("next_cursor") if isinstance(meta, dict) else ""
            if not isinstance(cursor, str) or not cursor:
                break
        return out

    def channels(self) -> list[dict]:
        """[{id, name, is_private, is_member}] of public and private channels the token can see."""
        rows = self._list("conversations.list", "channels", {
            "types": "public_channel,private_channel", "exclude_archived": "true", "limit": 200})
        return [{"id": c["id"], "name": str(c.get("name") or c["id"]), "is_private": bool(c.get("is_private")),
                 "is_member": bool(c.get("is_member"))} for c in rows if isinstance(c.get("id"), str)]

    def users(self) -> dict[str, str]:
        """user id -> display name (profile.display_name, else real_name, else name); deleted users skipped."""
        out = {}
        for u in self._list("users.list", "members", {"limit": 200}):
            if u.get("deleted") or not isinstance(u.get("id"), str):
                continue
            profile = u.get("profile") if isinstance(u.get("profile"), dict) else {}
            out[u["id"]] = str(profile.get("display_name") or u.get("real_name") or u.get("name") or u["id"])
        return out

    def _request(self, method: str, params: dict) -> dict:
        response = self.transport.get(
            f"{API_BASE}/{method}?{urlencode(params)}",
            {
                "Accept": "application/json",
                "User-Agent": "hackfront/0.1",
                **({"Authorization": f"Bearer {self.token}"} if self.token else {}),
            },
            self.timeout,
        )
        if not 200 <= response.status < 300:
            raise SlackAPIError(f"Slack API returned HTTP {response.status}", response.status)
        try:
            payload = json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise SlackAPIError("Slack API returned invalid JSON", response.status) from None
        if not isinstance(payload, dict) or payload.get("ok") is not True:
            code = payload.get("error") if isinstance(payload, dict) else None  # e.g. not_in_channel
            raise SlackAPIError(f"Slack API error: {code if isinstance(code, str) and code.isidentifier() else 'unsuccessful'}",
                                response.status)
        return payload

    def thread_page(
        self,
        channel: str,
        thread_ts: str,
        *,
        cursor: str | None = None,
        limit: int = MAX_PAGE_SIZE,
    ) -> Page:
        if not channel or not thread_ts:
            raise ValueError("channel and thread_ts are required")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        params = {"channel": channel, "ts": thread_ts, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._call("conversations.replies", params)

    def history_page(self, channel: str, *, cursor: str | None = None, limit: int = MAX_PAGE_SIZE) -> Page:
        """Top-level channel messages (thread roots and standalone messages), newest first."""
        if not channel:
            raise ValueError("channel is required")
        if not 1 <= limit <= MAX_PAGE_SIZE:
            raise ValueError(f"limit must be between 1 and {MAX_PAGE_SIZE}")
        params = {"channel": channel, "limit": limit}
        if cursor:
            params["cursor"] = cursor
        return self._call("conversations.history", params)
