"""Slack thread adapter."""

from __future__ import annotations

from dataclasses import dataclass

from ...contracts import Artifact
from .client import SlackClient
from .mapper import map_thread_message


@dataclass(frozen=True, slots=True)
class ArtifactPage:
    items: tuple[Artifact, ...]
    next_cursor: str | None


class SlackAdapter:
    def __init__(self, client: SlackClient):
        self.client = client

    def history_page(
        self, workspace: str, channel: str, *, cursor: str | None = None, limit: int = 15,
    ) -> ArtifactPage:
        """Thread roots / standalone messages of a channel; `context.reply_count` says whether to fetch replies."""
        if not workspace:
            raise ValueError("workspace is required for stable Slack identities")
        page = self.client.history_page(channel, cursor=cursor, limit=limit)
        # Replies broadcast to the channel carry thread_ts != ts; they are ingested via their thread instead.
        roots = [m for m in page.items if m.get("thread_ts") in (None, m.get("ts"))]
        return ArtifactPage(
            tuple(map_thread_message(m, workspace, channel, str(m["ts"])) for m in roots), page.next_cursor
        )

    def thread_page(
        self,
        workspace: str,
        channel: str,
        thread_ts: str,
        *,
        cursor: str | None = None,
        limit: int = 15,
    ) -> ArtifactPage:
        if not workspace:
            raise ValueError("workspace is required for stable Slack identities")
        page = self.client.thread_page(channel, thread_ts, cursor=cursor, limit=limit)
        return ArtifactPage(
            tuple(map_thread_message(message, workspace, channel, thread_ts) for message in page.items),
            page.next_cursor,
        )
