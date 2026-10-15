from hackfront.ingest.contracts import Artifact, Provenance, RecordKind, SourceIdentity
from hackfront.ingest.extraction.links import LinkConfig, add_text_references

CFG = LinkConfig(frozenset({"PAY", "SEC"}), "acme")


def art(provider, workspace, rtype, sid, text, kind=RecordKind.PULL_REQUEST, title=None):
    return Artifact(
        SourceIdentity(provider, workspace, rtype, sid), kind, "2026-03-04T09:30:00Z",
        Provenance("https://x/y", "$", "2026-03-04T09:30:00Z", "t/1"), title=title, text=text, raw_payload={},
    )


def ids(artifact):
    return {r.target.canonical_id: r for r in artifact.references}


def test_pr_body_links_jira_slack_and_pr():
    body = ("Fixes PAY-412. Decision in https://acme.slack.com/archives/C01PAY/p1772461200000100 "
            "see #190 and UTF-8, SHA-256, OTHER-9; color: #333; border #000000")
    out = ids(add_text_references(art("github", "acme/shop", "pull_request", "218", body), CFG))
    assert set(out) == {
        "jira:PAY:issue:PAY-412",
        "slack:acme:thread:1772461200.000100",
        "github:acme%2Fshop:pull_request:190",
    }
    ref = out["jira:PAY:issue:PAY-412"]
    assert ref.origin == "text" and ref.locator == "$.body#6-13"


def test_slack_reply_permalink_targets_message_and_wrong_workspace_ignored():
    text = ("https://acme.slack.com/archives/C1/p1772461500000200?thread_ts=1772461200.000100&cid=C1 "
            "https://other.slack.com/archives/C1/p1772461500000300")
    out = ids(add_text_references(art("jira", "PAY", "issue", "PAY-1", text, RecordKind.ISSUE), CFG))
    assert set(out) == {"slack:acme:message:1772461500.000200"}


def test_bare_hash_only_in_repo_records_and_commit_url_needs_full_sha():
    sha = "a" * 40
    t = f"see #5 https://github.com/acme/shop/commit/{sha} https://github.com/acme/shop/commit/abc1234"
    chat = art("slack", "acme", "message", "1.1", t, RecordKind.DISCUSSION_MESSAGE)
    assert set(ids(add_text_references(chat, CFG))) == {f"github:acme%2Fshop:commit:{sha}"}
    commit = art("github", "acme/shop", "commit", "b" * 40, t, RecordKind.GIT_COMMIT)
    assert "github:acme%2Fshop:pull_request:5" in ids(add_text_references(commit, CFG))


def test_no_self_link_and_dedupe_and_idempotent():
    a = art("jira", "PAY", "issue", "PAY-412", "PAY-412 again PAY-7 PAY-7", RecordKind.ISSUE)
    once = add_text_references(a, CFG)
    assert set(ids(once)) == {"jira:PAY:issue:PAY-7"} and len(once.references) == 1
    assert add_text_references(once, CFG).references == once.references


def test_slack_ts_boundary_and_query_string_url():
    t = ("https://acme.slack.com/archives/C1/p17000000001234567890 "
         "https://x.example/?next=https://github.com/acme/shop/pull/7")
    assert not ids(add_text_references(art("jira", "PAY", "issue", "PAY-1", t, RecordKind.ISSUE), CFG))
