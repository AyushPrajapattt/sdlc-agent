"""Cursor-aware GitHub commit and pull-request source adapter."""

from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Mapping

from ...contracts import Artifact, RelationshipKind, SourceIdentity, SourceReference
from .client import GitHubClient, Page
from .mapper import map_commit, map_pull_request, map_pull_request_activity


def _html_url(commit: Mapping[str, object]) -> str | None:
    url = commit.get("html_url")
    return url if isinstance(url, str) and url else None


@dataclass(frozen=True, slots=True)
class ArtifactPage:
    items: tuple[Artifact, ...]
    next_cursor: str | None


class GitHubAdapter:
    """Fetches source-native GitHub history and PRs, then maps each page."""

    def __init__(self, client: GitHubClient):
        self.client = client

    @staticmethod
    def _repo(owner: str, repository: str) -> str:
        if not owner or not repository or any(char in owner + repository for char in "/?#"):
            raise ValueError("owner and repository must be simple path segments")
        return f"{owner}/{repository}"

    def commits_page(
        self,
        owner: str,
        repository: str,
        *,
        cursor: str | None = None,
        since: str | None = None,
        per_page: int = 100,
    ) -> ArtifactPage:
        self._repo(owner, repository)
        params = {"since": since} if since and cursor is None else None
        page: Page = self.client.get_page(
            self.client.repository_path(owner, repository, "commits"),
            cursor=cursor,
            per_page=per_page,
            params=params,
        )
        artifacts: list[Artifact] = []
        for summary in page.items:
            payload: Mapping[str, object] = summary
            sha = summary.get("sha")
            if not isinstance(sha, str) or not sha:
                raise ValueError("GitHub commit list item is missing sha")
            if not isinstance(summary.get("files"), list) or not isinstance(summary.get("stats"), dict):
                url = summary.get("url")
                if not isinstance(url, str) or not url:
                    raise ValueError("GitHub commit list item is missing its detail URL")
                payload = self.client.get_resource(url)
            artifacts.append(map_commit(payload, owner, repository))
        return ArtifactPage(tuple(artifacts), page.next_cursor)

    def pull_requests_page(
        self,
        owner: str,
        repository: str,
        *,
        cursor: str | None = None,
        state: str = "all",
        per_page: int = 100,
    ) -> ArtifactPage:
        self._repo(owner, repository)
        if state not in {"open", "closed", "all"}:
            raise ValueError("state must be open, closed, or all")
        page = self.client.get_page(
            self.client.repository_path(owner, repository, "pulls"),
            cursor=cursor,
            per_page=per_page,
            params=None if cursor else {"state": state, "sort": "updated", "direction": "desc"},
        )
        return ArtifactPage(
            tuple(self._with_commits(map_pull_request(p, owner, repository), owner, repository) for p in page.items),
            page.next_cursor,
        )

    def _with_commits(self, pull: Artifact, owner: str, repository: str) -> Artifact:
        """PR CONTAINS each commit listed by the PR commits endpoint (the source's own statement)."""
        number = pull.source.source_id
        # ponytail: first page only (100 commits per PR); follow cursors if PRs that large matter.
        page = self.client.get_page(
            self.client.repository_path(owner, repository, f"pulls/{number}/commits"), per_page=100
        )
        contained = tuple(
            SourceReference(
                SourceIdentity("github", f"{owner}/{repository}", "commit", str(c["sha"]), _html_url(c)),
                RelationshipKind.CONTAINS,
                f"endpoint:/repos/{owner}/{repository}/pulls/{number}/commits[{i}].sha",
            )
            for i, c in enumerate(page.items) if isinstance(c.get("sha"), str) and c["sha"]
        )
        return replace(pull, references=pull.references + contained)

    def pull_request_activity_page(
        self,
        owner: str,
        repository: str,
        pull_number: int,
        activity: str,
        *,
        cursor: str | None = None,
        per_page: int = 100,
    ) -> ArtifactPage:
        """Fetch one bounded page of reviews, inline review comments, or PR comments."""
        self._repo(owner, repository)
        if not isinstance(pull_number, int) or pull_number < 1:
            raise ValueError("pull_number must be a positive integer")
        if activity not in {"reviews", "review_comments", "issue_comments"}:
            raise ValueError("activity must be reviews, review_comments, or issue_comments")
        paths = {
            "reviews": f"pulls/{pull_number}/reviews",
            "review_comments": f"pulls/{pull_number}/comments",
            "issue_comments": f"issues/{pull_number}/comments",
        }
        page = self.client.get_page(
            self.client.repository_path(owner, repository, paths[activity]),
            cursor=cursor,
            per_page=per_page,
        )
        return ArtifactPage(
            tuple(
                map_pull_request_activity(payload, owner, repository, pull_number, activity)
                for payload in page.items
            ),
            page.next_cursor,
        )

    def pull_request_reviews_page(self, owner: str, repository: str, pull_number: int, **kwargs) -> ArtifactPage:
        return self.pull_request_activity_page(owner, repository, pull_number, "reviews", **kwargs)

    def pull_request_review_comments_page(self, owner: str, repository: str, pull_number: int, **kwargs) -> ArtifactPage:
        return self.pull_request_activity_page(owner, repository, pull_number, "review_comments", **kwargs)

    def pull_request_issue_comments_page(self, owner: str, repository: str, pull_number: int, **kwargs) -> ArtifactPage:
        return self.pull_request_activity_page(owner, repository, pull_number, "issue_comments", **kwargs)
