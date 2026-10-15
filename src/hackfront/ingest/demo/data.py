"""Synthetic 'acme-demo/shop' workspace as native-shaped GitHub, Jira and Slack API payloads.

Two linked stories plus noise and one question the data cannot answer:
  A. Why are gateway retries capped at 3?   PAY-412 -> #payments-incident -> PR #218 -> 2 commits
  B. Why is the session TTL 15 minutes?     SEC-77 -> PR #190 -> #support pushback -> PR #201
  C. Why Redis for the session cache?       a thread asks; nobody knows (evidence is NOT sufficient)
All content is invented; there are no real people, secrets or customers.
"""

from __future__ import annotations

import difflib
import hashlib
from datetime import datetime, timezone

OWNER, REPO = "acme-demo", "shop"
GH = f"https://github.com/{OWNER}/{REPO}"
API = f"https://api.github.com/repos/{OWNER}/{REPO}"
JIRA_SITE = "https://acme-demo.atlassian.net"
SLACK_WS = "acme-demo"


def t(s: str) -> datetime:
    return datetime.fromisoformat(s).astimezone(timezone.utc)


def iso(d: datetime) -> str:
    return d.strftime("%Y-%m-%dT%H:%M:%SZ")


def sha(label: str) -> str:
    return hashlib.sha1(label.encode()).hexdigest()


def ts(d: datetime, n: int = 1) -> str:
    return f"{int(d.timestamp())}.{n:06d}"


def permalink(channel: str, slack_ts: str) -> str:
    return f"https://{SLACK_WS}.slack.com/archives/{channel}/p{slack_ts.replace('.', '')}"


def user(login: str, uid: int) -> dict:
    return {"login": login, "id": uid, "type": "User", "html_url": f"https://github.com/{login}"}


RAJ, DANA, MIRA, LEE = user("raj-k", 1001), user("dana-p", 1002), user("mira-s", 1003), user("lee-m", 1004)


# ---------------------------------------------------------------- GitHub
# File histories are consistent by construction: every version of a file is written out in full and each
# commit's patch is generated from consecutive versions with difflib, so replaying the patches reproduces
# FINAL_FILES exactly.
def diff(old: str, new: str) -> str:
    """Unified-diff hunks (no ---/+++ header) from old to new; a new file is `@@ -0,0 +1,N @@`."""
    rows = list(difflib.unified_diff(old.splitlines(), new.splitlines(), lineterm="", n=3))
    return "\n".join(rows[2:])


REQ0 = """# runtime
flask==3.0.3
requests==2.31.0
psycopg[binary]==3.1.19
"""
REQ1 = REQ0.replace("requests==2.31.0", "requests==2.32.4")

README0 = """Gateway charge retires are capped and every request carries an idempotency key.

See gateway_client.py for the retry policy.
"""
README1 = README0.replace("retires", "retries")

GATEWAY0 = """import random
import time

import requests

from .models import PaymentAttempt

MAX_RETRIES = 10
GATEWAY_URL = "https://api.stripe.invalid/v1/charges"


class GatewayClient:
    def __init__(self, session: requests.Session):
        self.session = session

    def charge(self, attempt: PaymentAttempt) -> dict:
        for _ in range(MAX_RETRIES):
            resp = self.session.post(GATEWAY_URL, json=attempt.payload)
            if resp.status_code < 500:
                return resp.json()
            time.sleep(1)
        raise GatewayUnavailable(attempt.order_id)
"""
GATEWAY1 = (GATEWAY0
            .replace("MAX_RETRIES = 10\nGATEWAY_URL = \"https://api.stripe.invalid/v1/charges\"\n",
                     "MAX_RETRIES = 3\nGATEWAY_URL = \"https://api.stripe.invalid/v1/charges\"\nBASE_DELAY_S = 0.25\n")
            .replace("for _ in range", "for n in range")
            .replace("time.sleep(1)", "time.sleep(random.uniform(0, BASE_DELAY_S * 2 ** n))"))
GATEWAY2 = (GATEWAY1
            .replace("        for n in range(MAX_RETRIES):\n",
                     "        headers = {\"Idempotency-Key\": attempt.idempotency_key}\n        for n in range(MAX_RETRIES):\n")
            .replace("json=attempt.payload)", "json=attempt.payload, headers=headers)"))

MODELS0 = """from dataclasses import dataclass


@dataclass
class PaymentAttempt:
    order_id: str
    no: int
    payload: dict
"""
MODELS1 = MODELS0 + "    idempotency_key: str\n"

SESSION0 = """import time

SESSION_TTL_SECONDS = 86400


class SessionCache:
    def __init__(self, store):
        self._store = store

    def get(self, token: str):
        entry = self._store.get(token)
        if entry is None:
            return None
        if time.time() - entry.last_seen > SESSION_TTL_SECONDS:
            self._store.delete(token)
            return None
        return entry
"""
SESSION1 = SESSION0.replace("86400", "900")
SESSION2 = (SESSION1.replace("import time\n\n", "import time\n\nfrom .refresh import refresh_on_activity\n\n")
            .replace("return entry\n", "return refresh_on_activity(entry)\n"))
REFRESH_PY = """import time


def refresh_on_activity(entry):
    # active users never hit the idle limit
    entry.last_seen = time.time()
    return entry
"""

FINAL_FILES = {  # path -> exact text after the newest commit
    "requirements.txt": REQ1,
    "src/payments/README.md": README1,
    "src/payments/gateway_client.py": GATEWAY2,
    "src/payments/models.py": MODELS1,
    "src/auth/session_cache.py": SESSION2,
    "src/auth/refresh.py": REFRESH_PY,
}


def commit(label: str, message: str, when: str, author: dict, files: list[tuple[str, str]], parents=()) -> dict:
    h = sha(label)
    date = iso(t(when))
    person = {"name": author["login"], "email": f"{author['login']}@acme-demo.example", "date": date}
    adds = sum(p.count("\n+") for _, p in files)
    dels = sum(p.count("\n-") for _, p in files)
    return {
        "sha": h, "url": f"{API}/commits/{h}", "html_url": f"{GH}/commit/{h}",
        "commit": {"message": message, "author": person, "committer": person},
        "author": author, "committer": author,
        "parents": [{"sha": p, "url": f"{API}/commits/{p}", "html_url": f"{GH}/commit/{p}"} for p in parents],
        "stats": {"additions": adds, "deletions": dels, "total": adds + dels},
        "files": [{"filename": f, "status": "added" if p.startswith("@@ -0,0 ") else "modified",
                   "additions": p.count("\n+"), "deletions": p.count("\n-"),
                   "changes": p.count("\n+") + p.count("\n-"), "patch": p} for f, p in files],
    }


# Base commits come first in time and in the parent chain; the stories build on them.
C_INIT = commit("init", "Add project scaffolding", "2025-12-01T09:00:00Z", DANA,
                [("requirements.txt", diff("", REQ0)), ("src/payments/README.md", diff("", README0))])
C_BASE_AUTH = commit("base-auth", "Add SessionCache", "2025-12-08T10:00:00Z", MIRA,
                     [("src/auth/session_cache.py", diff("", SESSION0))], [C_INIT["sha"]])
C_BASE_PAY = commit("base-pay", "Add GatewayClient", "2025-12-15T10:00:00Z", RAJ,
                    [("src/payments/gateway_client.py", diff("", GATEWAY0)),
                     ("src/payments/models.py", diff("", MODELS0))], [C_BASE_AUTH["sha"]])
C_BUMP = commit("bump", "Bump requests to 2.32.4\n\nDependabot.", "2026-01-05T06:00:00Z", DANA,
                [("requirements.txt", diff(REQ0, REQ1))], [C_BASE_PAY["sha"]])
C_TTL = commit("ttl", "Set SESSION_TTL_SECONDS to 900\n\nSEC-77: sessions must expire after 15 idle minutes.",
               "2026-01-26T16:40:00Z", MIRA,
               [("src/auth/session_cache.py", diff(SESSION0, SESSION1))],
               [C_BUMP["sha"]])
C_REFRESH = commit("refresh", "Add sliding refresh for active sessions (#201)", "2026-02-10T09:40:00Z", MIRA,
                   [("src/auth/session_cache.py", diff(SESSION1, SESSION2)),
                    ("src/auth/refresh.py", diff("", REFRESH_PY))],
                   [C_TTL["sha"]])
C_RETRY = commit("retry", "Reduce gateway MAX_RETRIES from 10 to 3\n\nPAY-412: retries amplified duplicate charges during the outage.",
                 "2026-03-03T17:12:00Z", RAJ,
                 [("src/payments/gateway_client.py", diff(GATEWAY0, GATEWAY1))],
                 [C_REFRESH["sha"]])
C_IDEM = commit("idem", "Send Idempotency-Key on every charge request (#218)\n\nKey is order_id:attempt_no, persisted on PaymentAttempt so retries reuse it.",
                "2026-03-04T08:55:00Z", RAJ,
                [("src/payments/gateway_client.py", diff(GATEWAY1, GATEWAY2)),
                 ("src/payments/models.py", diff(MODELS0, MODELS1))],
                [C_RETRY["sha"]])
C_TYPO = commit("typo", "Fix typo in payments README", "2026-03-06T12:00:00Z", DANA,
                [("src/payments/README.md", diff(README0, README1))], [C_IDEM["sha"]])
COMMITS = [C_TYPO, C_IDEM, C_RETRY, C_REFRESH, C_TTL, C_BUMP, C_BASE_PAY, C_BASE_AUTH, C_INIT]  # newest first, like the API

# Slack ids needed by PR text
T_PAY = t("2026-03-02T15:00:00Z")
PAY_ROOT, PAY_R1, PAY_R2 = ts(T_PAY, 100), ts(T_PAY.replace(minute=5), 200), ts(T_PAY.replace(minute=10), 300)
T_SUP = t("2026-02-05T13:20:00Z")
SUP_ROOT, SUP_R1 = ts(T_SUP, 100), ts(T_SUP.replace(minute=25), 200)
T_ENG = t("2026-02-12T10:00:00Z")
ENG_ROOT, ENG_R1 = ts(T_ENG, 100), ts(T_ENG.replace(minute=9), 200)


def pull(number: int, title: str, body: str, created: str, merged: bool, head: dict, base: dict, user_: dict) -> dict:
    return {
        "number": number, "id": 9000 + number, "url": f"{API}/pulls/{number}", "html_url": f"{GH}/pull/{number}",
        "state": "closed", "title": title, "body": body, "user": user_,
        "created_at": iso(t(created)), "updated_at": iso(t(created)), "merged": merged,
        "merge_commit_sha": head["sha"] if merged else None,
        "head": {"ref": f"feature/pr-{number}", "sha": head["sha"]},
        "base": {"ref": "main", "sha": base["sha"]},
        "additions": 5, "deletions": 2,
    }


PR_TYPO = pull(220, "Fix typo in payments README", "retires -> retries", "2026-03-06T11:00:00Z", True, C_TYPO, C_IDEM, DANA)
PR_RETRY = pull(
    218, "Cap gateway retries at 3 and add idempotency keys",
    f"Fixes PAY-412. Root cause and decision: {permalink('C01PAY', PAY_ROOT)}\n\n"
    "MAX_RETRIES 10 -> 3 with full-jitter backoff. Every charge sends Idempotency-Key = order_id:attempt_no. "
    "The cap stays at 3 for the 8s checkout latency budget.",
    "2026-03-04T09:30:00Z", True, C_IDEM, C_REFRESH, RAJ)
PR_REFRESH = pull(
    201, "Sliding refresh tokens for active sessions",
    f"Keeps the 15 min idle TTL from SEC-77 but refreshes on activity, per {permalink('C02SUP', SUP_ROOT)}. "
    f"Follows #190.",
    "2026-02-10T10:00:00Z", True, C_REFRESH, C_TTL, MIRA)
PR_TTL = pull(190, "Reduce session TTL to 15 minutes (SEC-77)",
              "Sets SESSION_TTL_SECONDS = 900 to satisfy the SEC-77 audit requirement.",
              "2026-01-27T11:00:00Z", True, C_TTL, C_BUMP, MIRA)
PULLS = [PR_TYPO, PR_RETRY, PR_REFRESH, PR_TTL]
PR_COMMITS = {  # /pulls/{n}/commits
    220: [C_TYPO], 218: [C_RETRY, C_IDEM], 201: [C_REFRESH], 190: [C_TTL],
}


def issue_comment(cid: int, body: str, when: str, author: dict, n: int) -> dict:
    return {"id": cid, "url": f"{API}/issues/comments/{cid}", "html_url": f"{GH}/pull/{n}#issuecomment-{cid}",
            "body": body, "user": author, "created_at": iso(t(when)), "updated_at": iso(t(when))}


PR_ISSUE_COMMENTS = {218: [issue_comment(
    7001, "LGTM. Please confirm 3 retries still fits the 8s checkout budget with jitter.", "2026-03-04T10:00:00Z", DANA, 218)]}
PR_REVIEWS = {218: [{
    "id": 8001, "html_url": f"{GH}/pull/218#pullrequestreview-8001", "user": DANA, "state": "APPROVED",
    "body": "Approved. Keep the cap at 3 even after idempotency lands.", "submitted_at": iso(t("2026-03-04T10:30:00Z")),
    "commit_id": C_IDEM["sha"]}]}
PR_REVIEW_COMMENTS = {218: [{
    "id": 6001, "url": f"{API}/pulls/comments/6001", "html_url": f"{GH}/pull/218#discussion_r6001", "user": DANA,
    "body": "Why not make this configurable? -> No: the 8s checkout latency budget makes >3 pointless (see PAY-412).",
    "path": "src/payments/gateway_client.py", "line": 8, "diff_hunk": C_RETRY["files"][0]["patch"],
    "commit_id": C_RETRY["sha"], "created_at": iso(t("2026-03-04T09:50:00Z")), "updated_at": iso(t("2026-03-04T09:50:00Z"))}]}


# ---------------------------------------------------------------- Jira (ADF bodies)
def adf(text: str) -> dict:
    return {"type": "doc", "version": 1, "content": [{"type": "paragraph", "content": [{"type": "text", "text": text}]}]}


def jira_issue(key: str, summary: str, description: str, created: str, itype: str, status: str, reporter: str) -> dict:
    project = key.split("-")[0]
    return {"id": str(10000 + int(key.split("-")[1])), "key": key, "self": f"{JIRA_SITE}/rest/api/3/issue/{key}",
            "fields": {"summary": summary, "description": adf(description), "issuetype": {"name": itype},
                       "project": {"key": project}, "status": {"name": status}, "priority": {"name": "High"},
                       "reporter": {"accountId": f"acc-{reporter}", "displayName": reporter},
                       "created": created, "updated": created, "labels": [], "issuelinks": []}}


JIRA_ISSUES = {
    "PAY": [jira_issue(
        "PAY-412", "Duplicate charges during Stripe gateway outage",
        "Incident 2026-03-02: 214 customers were charged 2-6 times. The gateway returned 502s for 11 minutes and "
        "GatewayClient retried each charge up to 10 times. Some 502s were returned AFTER the charge succeeded upstream, "
        "so every retry created a new charge. Actions: cap retries, add idempotency keys.",
        "2026-03-02T14:20:00.000+0000", "Bug", "Done", "dana-p")],
    "SEC": [jira_issue(
        "SEC-77", "Audit finding: session tokens valid for 24 hours",
        "External pen-test (Q1) rated 24h session tokens high risk for stolen-cookie replay. "
        "Requirement: idle session lifetime must be 15 minutes or less. Compliance item, not optional.",
        "2026-01-20T10:00:00.000+0000", "Task", "Done", "mira-s")],
}
JIRA_COMMENTS = {
    "PAY-412": [{"id": "30001", "self": f"{JIRA_SITE}/rest/api/3/issue/10412/comment/30001",
                 "author": {"accountId": "acc-raj-k", "displayName": "raj-k"},
                 "body": adf(f"Root cause and the retry decision are in {permalink('C01PAY', PAY_ROOT)}. Fix in {GH}/pull/218."),
                 "created": "2026-03-04T09:45:00.000+0000", "updated": "2026-03-04T09:45:00.000+0000"}],
    "SEC-77": [],
}


# ---------------------------------------------------------------- Slack
def smsg(ts_: str, user_: str, text: str, **extra) -> dict:
    return {"type": "message", "user": user_, "ts": ts_, "text": text, **extra}


SLACK_THREADS = {  # channel -> {thread_ts: [root, *replies]}
    "C01PAY": {PAY_ROOT: [
        smsg(PAY_ROOT, "U_DANA", "refunds done for PAY-412. How do we stop this happening again?",
             thread_ts=PAY_ROOT, reply_count=2),
        smsg(PAY_R1, "U_RAJ", "10 retries with no idempotency key is the root cause. Stripe dedupes on Idempotency-Key for 24h. "
             "Proposal: send a key per order attempt and drop retries to 3 with jittered backoff. 3 covers 99.2% of "
             "transient 502s in last quarter's logs; beyond that we fail fast and let the order queue retry later.",
             thread_ts=PAY_ROOT),
        smsg(PAY_R2, "U_DANA", "agreed. Raj owns it, tracked in PAY-412. Keep 3 even after idempotency lands: the checkout "
             "latency budget is 8s and 10 retries blew through it anyway.", thread_ts=PAY_ROOT)]},
    "C02SUP": {SUP_ROOT: [
        smsg(SUP_ROOT, "U_LEE", f"lots of tickets about being logged out mid-checkout since {GH}/pull/190. Can we revert the 15 min TTL?",
             thread_ts=SUP_ROOT, reply_count=1),
        smsg(SUP_R1, "U_MIRA", "can't revert, SEC-77 is a compliance item. We'll add sliding refresh tokens instead so "
             "active users never hit the 15 min idle limit.", thread_ts=SUP_ROOT)]},
    "C03ENG": {ENG_ROOT: [
        smsg(ENG_ROOT, "U_LEE", "anyone know why we picked Redis for the session cache?", thread_ts=ENG_ROOT, reply_count=1),
        smsg(ENG_R1, "U_RAJ", "no idea, it predates me. Not written down anywhere I can find.", thread_ts=ENG_ROOT)]},
}
