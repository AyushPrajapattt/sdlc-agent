"""Explicit cross-source references found in text.

Only identifiers a human wrote down become edges: Jira keys of configured projects, GitHub PR and
full-SHA commit URLs, `#N` in GitHub records, Slack permalinks. No fuzzy or semantic matching;
every edge carries origin="text" and a locator naming the source field and character span.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from ..contracts import Artifact, RelationshipKind, SourceIdentity, SourceReference

JIRA_KEY = re.compile(r"\b([A-Z][A-Z0-9]{1,9})-(\d{1,6})\b")
GH_PR_URL = re.compile(r"(?<![=&?])https?://github\.com/([\w.-]+)/([\w.-]+)/pull/(\d+)")
GH_COMMIT_URL = re.compile(r"(?<![=&?])https?://github\.com/([\w.-]+)/([\w.-]+)/commit/([0-9a-f]{40})\b")
# "(#218)" (squash-merge titles) or "PR #218" / "fixes #218" style; never a bare "#333" (CSS colours, anchors)
BARE_PR = re.compile(r"\(#(\d{1,7})\)|(?i:\b(?:pr|pull|fixes|closes|resolves|refs|see|follows|reverts))\s+#(\d{1,7})\b")
SLACK_LINK = re.compile(r"https?://([\w-]+)\.slack\.com/archives/([A-Z0-9]+)/p(\d{10})(\d{6})(?!\d)(\?[^\s>|)]*)?")


@dataclass(frozen=True, slots=True)
class LinkConfig:
    jira_projects: frozenset[str] = frozenset()
    slack_workspace: str = ""

    @classmethod
    def from_workspace(cls, workspace: dict) -> "LinkConfig":
        return cls(frozenset(workspace["jira"]["projects"]), workspace["slack"]["workspace"])


def _text_fields(artifact: Artifact) -> tuple[tuple[str, str | None], ...]:
    """(source locator, text) pairs; locators follow the native payload shape."""
    provider, kind = artifact.source.provider, artifact.source.record_type
    if provider == "github" and kind == "commit":
        return (("$.commit.message", artifact.text),)
    if provider == "github" and kind == "pull_request":
        return (("$.title", artifact.title), ("$.body", artifact.text))
    if provider == "jira" and kind == "issue":
        return (("$.fields.summary", artifact.title), ("$.fields.description", artifact.text))
    return (("$.body" if provider in ("github", "jira") else "$.text", artifact.text),)


def _refs_in(text: str, locator: str, artifact: Artifact, config: LinkConfig) -> list[SourceReference]:
    found: list[tuple[int, int, SourceIdentity]] = []
    provider, workspace = artifact.source.provider, artifact.source.workspace

    for m in JIRA_KEY.finditer(text):
        if m.group(1) in config.jira_projects:
            found.append((m.start(), m.end(), SourceIdentity("jira", m.group(1), "issue", m.group(0))))
    for m in GH_PR_URL.finditer(text):
        found.append((m.start(), m.end(), SourceIdentity(
            "github", f"{m.group(1)}/{m.group(2)}", "pull_request", m.group(3), m.group(0))))
    for m in GH_COMMIT_URL.finditer(text):
        found.append((m.start(), m.end(), SourceIdentity(
            "github", f"{m.group(1)}/{m.group(2)}", "commit", m.group(3), m.group(0))))
    if provider == "github":  # bare #N is only meaningful inside its own repository
        for m in BARE_PR.finditer(text):
            found.append((m.start(), m.end(), SourceIdentity(
                "github", workspace, "pull_request", m.group(1) or m.group(2))))
    for m in SLACK_LINK.finditer(text):
        if config.slack_workspace and m.group(1) != config.slack_workspace:
            continue
        ts = f"{m.group(3)}.{m.group(4)}"
        thread_ts = re.search(r"[?&]thread_ts=(\d+\.\d+)", m.group(5) or "")
        is_reply = thread_ts is not None and thread_ts.group(1) != ts
        found.append((m.start(), m.end(), SourceIdentity(
            "slack", m.group(1), "message" if is_reply else "thread", ts, m.group(0))))

    return [
        SourceReference(target, RelationshipKind.REFERENCES, f"{locator}#{start}-{end}", origin="text")
        for start, end, target in found
    ]


def add_text_references(artifact: Artifact, config: LinkConfig) -> Artifact:
    """Return the artifact with extra `origin=text` references; one edge per distinct target."""
    seen = {(r.target.canonical_id, r.relationship) for r in artifact.references}
    seen.add((artifact.canonical_id, RelationshipKind.REFERENCES))  # never self-link
    extra: list[SourceReference] = []
    for locator, text in _text_fields(artifact):
        if not text:
            continue
        for ref in _refs_in(text, locator, artifact, config):
            key = (ref.target.canonical_id, ref.relationship)
            if key not in seen:
                seen.add(key)
                extra.append(ref)
    return replace(artifact, references=artifact.references + tuple(extra)) if extra else artifact
