"""In-memory stand-in for the Neo4j graph: same node properties, same relationship kinds,
same row shape as investigator.CYPHER, so `run_tool` is a drop-in replacement.

Two real "why" stories plus noise, across GitHub, Jira, and Slack:
  A. Why are payment gateway retries capped at 3?   (incident PAY-412 -> Slack -> PR #218)
  B. Why is the session TTL 15 minutes?              (audit SEC-77 -> PR #190 -> pushback -> PR #201)

Try:  python agent/investigator.py "Why are gateway retries capped at 3?"
"""

GH, JIRA, SLACK = "github:acme%2Fshop", "jira:acme", "slack:acme"


def node(cid, kind, title, text, url, time, paths=None):
    return {"id": cid, "kind": kind, "title": title, "text": text, "url": url, "time": time, "paths": paths}


NODES = [
    # --- Story A: retry cap --------------------------------------------------------------------------
    node(f"{JIRA}:issue:PAY-412", "issue", "Duplicate charges during Stripe gateway outage",
         "Incident 2026-03-02: 214 customers charged 2-6 times. Gateway returned 502s for 11 minutes; "
         "GatewayClient retried each charge up to 10 times. Some 502s were returned AFTER the charge "
         "succeeded upstream, so every retry created a new charge. Action items: cap retries, add idempotency keys.",
         "https://acme.atlassian.invalid/browse/PAY-412", "2026-03-02T14:20:00+00:00"),
    node(f"{SLACK}:thread:1772461200.000100", "discussion_thread", "#payments-incident",
         "@dana: refunds done for PAY-412. How do we stop this happening again?",
         "https://acme.slack.invalid/archives/C01PAY/p1772461200000100", "2026-03-02T15:00:00+00:00"),
    node(f"{SLACK}:message:1772461500.000200", "discussion_message", None,
         "@raj: 10 retries with no idempotency key is the root cause. Stripe dedupes on Idempotency-Key for 24h. "
         "Proposal: send a key per order attempt and drop retries to 3 with jittered backoff. 3 covers 99.2% of "
         "transient 502s in last quarter's logs; beyond that we should fail fast and let the order queue retry later.",
         "https://acme.slack.invalid/archives/C01PAY/p1772461500000200", "2026-03-02T15:05:00+00:00"),
    node(f"{SLACK}:message:1772461800.000300", "discussion_message", None,
         "@dana: agreed. Raj owns it, tracked in PAY-412. Keep 3 even after idempotency lands - latency budget for "
         "checkout is 8s and 10 retries blew through it anyway.",
         "https://acme.slack.invalid/archives/C01PAY/p1772461800000300", "2026-03-02T15:10:00+00:00"),
    node(f"{GH}:pull_request:218", "pull_request", "Cap gateway retries at 3 and add idempotency keys",
         "Fixes PAY-412. Root cause and decision in #payments-incident. MAX_RETRIES 10 -> 3 with full-jitter "
         "backoff; every charge sends Idempotency-Key = order_id:attempt_no. Retry cap stays at 3 for the 8s "
         "checkout latency budget.",
         "https://github.invalid/acme/shop/pull/218", "2026-03-04T09:30:00+00:00",
         ["src/payments/gateway_client.py", "src/payments/models.py"]),
    node(f"{GH}:commit:a1f3c9e", "git_commit", "Reduce gateway MAX_RETRIES from 10 to 3",
         "PAY-412: retries amplified duplicate charges during the outage.",
         "https://github.invalid/acme/shop/commit/a1f3c9e", "2026-03-03T17:12:00+00:00",
         ["src/payments/gateway_client.py"]),
    node(f"{GH}:commit:b7d20f4", "git_commit", "Send Idempotency-Key on every charge request",
         "Key is order_id:attempt_no, persisted on PaymentAttempt so retries reuse it.",
         "https://github.invalid/acme/shop/commit/b7d20f4", "2026-03-04T08:55:00+00:00",
         ["src/payments/gateway_client.py", "src/payments/models.py"]),

    # --- Story B: session TTL ------------------------------------------------------------------------
    node(f"{JIRA}:issue:SEC-77", "issue", "Audit finding: session tokens valid for 24 hours",
         "External pen-test (Q1) flagged 24h session tokens as high risk for stolen-cookie replay. "
         "Requirement: idle session lifetime <= 15 minutes.",
         "https://acme.atlassian.invalid/browse/SEC-77", "2026-01-20T10:00:00+00:00"),
    node(f"{GH}:pull_request:190", "pull_request", "Reduce session TTL to 15 minutes (SEC-77)",
         "Sets SESSION_TTL_SECONDS = 900 to satisfy the SEC-77 audit requirement.",
         "https://github.invalid/acme/shop/pull/190", "2026-01-27T11:00:00+00:00",
         ["src/auth/session_cache.py"]),
    node(f"{GH}:commit:9a8b7c1", "git_commit", "Set SESSION_TTL_SECONDS to 900",
         "SEC-77.", "https://github.invalid/acme/shop/commit/9a8b7c1", "2026-01-26T16:40:00+00:00",
         ["src/auth/session_cache.py"]),
    node(f"{SLACK}:thread:1770300000.000100", "discussion_thread", "#support",
         "@lee: lots of tickets about being logged out mid-checkout since last week. Can we revert the 15 min TTL?",
         "https://acme.slack.invalid/archives/C02SUP/p1770300000000100", "2026-02-05T13:20:00+00:00"),
    node(f"{SLACK}:message:1770300300.000200", "discussion_message", None,
         "@mira (security): can't revert, SEC-77 is a compliance item. We'll add sliding refresh tokens instead so "
         "active users never hit the 15 min idle limit.",
         "https://acme.slack.invalid/archives/C02SUP/p1770300300000200", "2026-02-05T13:25:00+00:00"),
    node(f"{GH}:pull_request:201", "pull_request", "Sliding refresh tokens for active sessions",
         "Keeps 15 min idle TTL from SEC-77 but refreshes on activity, per #support discussion.",
         "https://github.invalid/acme/shop/pull/201", "2026-02-10T10:00:00+00:00",
         ["src/auth/session_cache.py", "src/auth/refresh.py"]),

    # --- Noise ---------------------------------------------------------------------------------------
    node(f"{GH}:commit:c0ffee1", "git_commit", "Bump requests to 2.32.4", "Dependabot.",
         "https://github.invalid/acme/shop/commit/c0ffee1", "2026-03-05T06:00:00+00:00", ["requirements.txt"]),
    node(f"{GH}:pull_request:220", "pull_request", "Fix typo in payments README", "retires -> retries",
         "https://github.invalid/acme/shop/pull/220", "2026-03-06T12:00:00+00:00", ["src/payments/README.md"]),
]

# (source, relationship, target) using the ingestion RelationshipKind values
EDGES = [
    (f"{GH}:pull_request:218", "CONTAINS", f"{GH}:commit:a1f3c9e"),
    (f"{GH}:pull_request:218", "CONTAINS", f"{GH}:commit:b7d20f4"),
    (f"{GH}:pull_request:218", "REFERENCES", f"{JIRA}:issue:PAY-412"),
    (f"{GH}:pull_request:218", "REFERENCES", f"{SLACK}:thread:1772461200.000100"),
    (f"{GH}:commit:b7d20f4", "REFERENCES", f"{GH}:commit:a1f3c9e"),
    (f"{SLACK}:message:1772461500.000200", "REPLIES_TO", f"{SLACK}:thread:1772461200.000100"),
    (f"{SLACK}:message:1772461800.000300", "REPLIES_TO", f"{SLACK}:thread:1772461200.000100"),
    (f"{SLACK}:thread:1772461200.000100", "REFERENCES", f"{JIRA}:issue:PAY-412"),
    (f"{GH}:pull_request:190", "CONTAINS", f"{GH}:commit:9a8b7c1"),
    (f"{GH}:pull_request:190", "REFERENCES", f"{JIRA}:issue:SEC-77"),
    (f"{SLACK}:message:1770300300.000200", "REPLIES_TO", f"{SLACK}:thread:1770300000.000100"),
    (f"{SLACK}:message:1770300300.000200", "REFERENCES", f"{JIRA}:issue:SEC-77"),
    (f"{GH}:pull_request:201", "REFERENCES", f"{JIRA}:issue:SEC-77"),
    (f"{GH}:pull_request:201", "REFERENCES", f"{SLACK}:thread:1770300000.000100"),
]

BY_ID = {n["id"]: n for n in NODES}
ROW_LIMIT = 10


def _row(n):
    return {**n, "text": (n["text"] or "")[:600]}


def run_tool(call) -> list[dict]:
    """Same contract as investigator.run_tool: `call.tool` in search_text | search_path | expand."""
    arg = call.arg
    if call.tool == "search_text":
        hits = [n for n in NODES if arg.lower() in f"{n['title'] or ''} {n['text'] or ''}".lower()]
    elif call.tool == "search_path":
        hits = [n for n in NODES if any(arg in p for p in n["paths"] or [])]
    elif call.tool == "expand":  # undirected 1-hop, like ()-[]-()
        ids = [t for s, _, t in EDGES if s == arg] + [s for s, _, t in EDGES if t == arg]
        hits = [BY_ID[i] for i in dict.fromkeys(ids)]
    else:
        raise ValueError(f"unknown tool {call.tool}")
    return [_row(n) for n in hits[:ROW_LIMIT]]


if __name__ == "__main__":
    from types import SimpleNamespace as C

    assert {r["id"] for r in run_tool(C(tool="search_path", arg="gateway_client"))} == {
        f"{GH}:pull_request:218", f"{GH}:commit:a1f3c9e", f"{GH}:commit:b7d20f4"}
    assert f"{JIRA}:issue:PAY-412" in {r["id"] for r in run_tool(C(tool="expand", arg=f"{GH}:pull_request:218"))}
    assert len(run_tool(C(tool="search_text", arg="SEC-77"))) >= 4
    assert all(set(r) == {"id", "kind", "title", "text", "url", "time", "paths"} for r in
               run_tool(C(tool="search_text", arg="a")))
    print(f"mock graph ok: {len(NODES)} nodes, {len(EDGES)} edges")
