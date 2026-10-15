// Mock data, shaped like agent/mock_graph.py (same node kinds, relationship kinds, stories).
// Swap this module for a fetch to the investigator API later; the UI only reads these types.

export type Kind = "issue" | "discussion" | "pr" | "commit";
export type Status = "supported" | "inferred" | "unknown";

export interface Node {
  id: string;
  cid: string; // canonical id as stored in Neo4j
  kind: Kind;
  source: "jira" | "github" | "slack";
  ref: string; // short human label
  title: string;
  text: string;
  author: string;
  time: string;
  url: string;
  paths?: string[];
}

export interface Edge {
  from: string;
  to: string;
  rel: "CONTAINS" | "REFERENCES" | "REPLIES_TO" | "INFERRED";
  why?: string; // only for inferred edges
}

export interface Cite {
  node: string;
  quote?: string;
}
export interface Claim {
  id: string;
  text: string;
  status: Status;
  note?: string;
  cites: Cite[];
  afterStep: number; // revealed once the trace reaches this step
}
export interface Step {
  kind: "understand" | "plan" | "tool" | "gap" | "synthesize";
  label: string;
  detail: string;
  ms: number;
}
export interface Check {
  label: string;
  state: "holds" | "changed" | "unknown";
  detail: string;
}
export interface Investigation {
  id: string;
  question: string;
  file: string;
  line: number;
  summary: string;
  nodes: string[];
  claims: Claim[];
  gaps: string[];
  trace: Step[];
  checks: Check[];
  excluded: { node: string; reason: string }[];
}
export interface CodeLine {
  text: string;
  blame: string; // node id of commit
}
export interface CodeFile {
  path: string;
  lines: CodeLine[];
}

const n = (x: Omit<Node, "cid"> & { cid: string }): Node => x;

export const NODES: Record<string, Node> = Object.fromEntries(
  [
    // ---- Story A: retry cap
    n({ id: "pay412", cid: "jira:acme:issue:PAY-412", kind: "issue", source: "jira", ref: "PAY-412", author: "dana", time: "2026-03-02T14:20:00Z",
      title: "Duplicate charges during Stripe gateway outage",
      text: "Incident 2026-03-02: 214 customers charged 2-6 times. Gateway returned 502s for 11 minutes; GatewayClient retried each charge up to 10 times. Some 502s were returned AFTER the charge succeeded upstream, so every retry created a new charge. Action items: cap retries, add idempotency keys.",
      url: "https://acme.atlassian.invalid/browse/PAY-412" }),
    n({ id: "thrA", cid: "slack:acme:thread:1772461200.000100", kind: "discussion", source: "slack", ref: "#payments-incident", author: "dana", time: "2026-03-02T15:00:00Z",
      title: "#payments-incident",
      text: "@dana: refunds done for PAY-412. How do we stop this happening again?",
      url: "https://acme.slack.invalid/archives/C01PAY/p1772461200000100" }),
    n({ id: "msgRaj", cid: "slack:acme:message:1772461500.000200", kind: "discussion", source: "slack", ref: "@raj", author: "raj", time: "2026-03-02T15:05:00Z",
      title: "Reply in #payments-incident",
      text: "@raj: 10 retries with no idempotency key is the root cause. Stripe dedupes on Idempotency-Key for 24h. Proposal: send a key per order attempt and drop retries to 3 with jittered backoff. 3 covers 99.2% of transient 502s in last quarter's logs; beyond that we should fail fast and let the order queue retry later.",
      url: "https://acme.slack.invalid/archives/C01PAY/p1772461500000200" }),
    n({ id: "msgDana", cid: "slack:acme:message:1772461800.000300", kind: "discussion", source: "slack", ref: "@dana", author: "dana", time: "2026-03-02T15:10:00Z",
      title: "Reply in #payments-incident",
      text: "@dana: agreed. Raj owns it, tracked in PAY-412. Keep 3 even after idempotency lands - latency budget for checkout is 8s and 10 retries blew through it anyway.",
      url: "https://acme.slack.invalid/archives/C01PAY/p1772461800000300" }),
    n({ id: "pr218", cid: "github:acme/shop:pull_request:218", kind: "pr", source: "github", ref: "#218", author: "raj", time: "2026-03-04T09:30:00Z",
      title: "Cap gateway retries at 3 and add idempotency keys",
      text: "Fixes PAY-412. Root cause and decision in #payments-incident. MAX_RETRIES 10 -> 3 with full-jitter backoff; every charge sends Idempotency-Key = order_id:attempt_no. Retry cap stays at 3 for the 8s checkout latency budget.",
      url: "https://github.invalid/acme/shop/pull/218", paths: ["src/payments/gateway_client.py", "src/payments/models.py"] }),
    n({ id: "ca1f3c9e", cid: "github:acme/shop:commit:a1f3c9e", kind: "commit", source: "github", ref: "a1f3c9e", author: "raj", time: "2026-03-03T17:12:00Z",
      title: "Reduce gateway MAX_RETRIES from 10 to 3",
      text: "PAY-412: retries amplified duplicate charges during the outage.",
      url: "https://github.invalid/acme/shop/commit/a1f3c9e", paths: ["src/payments/gateway_client.py"] }),
    n({ id: "cb7d20f4", cid: "github:acme/shop:commit:b7d20f4", kind: "commit", source: "github", ref: "b7d20f4", author: "raj", time: "2026-03-04T08:55:00Z",
      title: "Send Idempotency-Key on every charge request",
      text: "Key is order_id:attempt_no, persisted on PaymentAttempt so retries reuse it.",
      url: "https://github.invalid/acme/shop/commit/b7d20f4", paths: ["src/payments/gateway_client.py", "src/payments/models.py"] }),
    n({ id: "ce4d5a10", cid: "github:acme/shop:commit:e4d5a10", kind: "commit", source: "github", ref: "e4d5a10", author: "sam", time: "2025-11-12T10:03:00Z",
      title: "Add GatewayClient",
      text: "Initial Stripe gateway wrapper.",
      url: "https://github.invalid/acme/shop/commit/e4d5a10", paths: ["src/payments/gateway_client.py"] }),

    // ---- Story B: session TTL
    n({ id: "sec77", cid: "jira:acme:issue:SEC-77", kind: "issue", source: "jira", ref: "SEC-77", author: "mira", time: "2026-01-20T10:00:00Z",
      title: "Audit finding: session tokens valid for 24 hours",
      text: "External pen-test (Q1) flagged 24h session tokens as high risk for stolen-cookie replay. Requirement: idle session lifetime <= 15 minutes.",
      url: "https://acme.atlassian.invalid/browse/SEC-77" }),
    n({ id: "c9a8b7c1", cid: "github:acme/shop:commit:9a8b7c1", kind: "commit", source: "github", ref: "9a8b7c1", author: "mira", time: "2026-01-26T16:40:00Z",
      title: "Set SESSION_TTL_SECONDS to 900", text: "SEC-77.",
      url: "https://github.invalid/acme/shop/commit/9a8b7c1", paths: ["src/auth/session_cache.py"] }),
    n({ id: "pr190", cid: "github:acme/shop:pull_request:190", kind: "pr", source: "github", ref: "#190", author: "mira", time: "2026-01-27T11:00:00Z",
      title: "Reduce session TTL to 15 minutes (SEC-77)",
      text: "Sets SESSION_TTL_SECONDS = 900 to satisfy the SEC-77 audit requirement.",
      url: "https://github.invalid/acme/shop/pull/190", paths: ["src/auth/session_cache.py"] }),
    n({ id: "thrB", cid: "slack:acme:thread:1770300000.000100", kind: "discussion", source: "slack", ref: "#support", author: "lee", time: "2026-02-05T13:20:00Z",
      title: "#support",
      text: "@lee: lots of tickets about being logged out mid-checkout since last week. Can we revert the 15 min TTL?",
      url: "https://acme.slack.invalid/archives/C02SUP/p1770300000000100" }),
    n({ id: "msgMira", cid: "slack:acme:message:1770300300.000200", kind: "discussion", source: "slack", ref: "@mira", author: "mira", time: "2026-02-05T13:25:00Z",
      title: "Reply in #support",
      text: "@mira (security): can't revert, SEC-77 is a compliance item. We'll add sliding refresh tokens instead so active users never hit the 15 min idle limit.",
      url: "https://acme.slack.invalid/archives/C02SUP/p1770300300000200" }),
    n({ id: "pr201", cid: "github:acme/shop:pull_request:201", kind: "pr", source: "github", ref: "#201", author: "mira", time: "2026-02-10T10:00:00Z",
      title: "Sliding refresh tokens for active sessions",
      text: "Keeps 15 min idle TTL from SEC-77 but refreshes on activity, per #support discussion.",
      url: "https://github.invalid/acme/shop/pull/201", paths: ["src/auth/session_cache.py", "src/auth/refresh.py"] }),
    n({ id: "cd4e5f60", cid: "github:acme/shop:commit:d4e5f60", kind: "commit", source: "github", ref: "d4e5f60", author: "mira", time: "2026-02-09T15:30:00Z",
      title: "Refresh session on activity", text: "Slides last_seen forward on each authenticated request.",
      url: "https://github.invalid/acme/shop/commit/d4e5f60", paths: ["src/auth/session_cache.py", "src/auth/refresh.py"] }),
    n({ id: "c7c2e8b3", cid: "github:acme/shop:commit:7c2e8b3", kind: "commit", source: "github", ref: "7c2e8b3", author: "sam", time: "2025-10-02T09:12:00Z",
      title: "Add SessionCache", text: "In-memory session cache with TTL eviction.",
      url: "https://github.invalid/acme/shop/commit/7c2e8b3", paths: ["src/auth/session_cache.py"] }),

    // ---- Noise
    n({ id: "cc0ffee1", cid: "github:acme/shop:commit:c0ffee1", kind: "commit", source: "github", ref: "c0ffee1", author: "dependabot", time: "2026-03-05T06:00:00Z",
      title: "Bump requests to 2.32.4", text: "Dependabot.", url: "https://github.invalid/acme/shop/commit/c0ffee1", paths: ["requirements.txt"] }),
    n({ id: "pr220", cid: "github:acme/shop:pull_request:220", kind: "pr", source: "github", ref: "#220", author: "lee", time: "2026-03-06T12:00:00Z",
      title: "Fix typo in payments README", text: "retires -> retries", url: "https://github.invalid/acme/shop/pull/220", paths: ["src/payments/README.md"] }),
  ].map((x) => [x.id, x]),
);

export const EDGES: Edge[] = [
  { from: "pr218", to: "ca1f3c9e", rel: "CONTAINS" },
  { from: "pr218", to: "cb7d20f4", rel: "CONTAINS" },
  { from: "pr218", to: "pay412", rel: "REFERENCES" },
  { from: "pr218", to: "thrA", rel: "REFERENCES" },
  { from: "cb7d20f4", to: "ca1f3c9e", rel: "REFERENCES" },
  { from: "msgRaj", to: "thrA", rel: "REPLIES_TO" },
  { from: "msgDana", to: "thrA", rel: "REPLIES_TO" },
  { from: "thrA", to: "pay412", rel: "REFERENCES" },
  { from: "msgRaj", to: "ca1f3c9e", rel: "INFERRED", why: "Message proposes 'drop retries to 3'; commit title matches. No explicit link in either source." },
  { from: "pr190", to: "c9a8b7c1", rel: "CONTAINS" },
  { from: "pr190", to: "sec77", rel: "REFERENCES" },
  { from: "msgMira", to: "thrB", rel: "REPLIES_TO" },
  { from: "msgMira", to: "sec77", rel: "REFERENCES" },
  { from: "pr201", to: "sec77", rel: "REFERENCES" },
  { from: "pr201", to: "thrB", rel: "REFERENCES" },
  { from: "pr201", to: "cd4e5f60", rel: "CONTAINS" },
  { from: "msgMira", to: "pr201", rel: "INFERRED", why: "Message proposes 'sliding refresh tokens'; PR #201 implements them 5 days later. No explicit link." },
];

const py = (rows: [string, string][]): CodeLine[] => rows.map(([text, blame]) => ({ text, blame }));

export const FILES: CodeFile[] = [
  {
    path: "src/payments/gateway_client.py",
    lines: py([
      ["import random", "ce4d5a10"],
      ["import time", "ce4d5a10"],
      ["", "ce4d5a10"],
      ["import requests", "ce4d5a10"],
      ["", "ce4d5a10"],
      ["from .models import PaymentAttempt", "ce4d5a10"],
      ["", "ce4d5a10"],
      ["MAX_RETRIES = 3", "ca1f3c9e"],
      ['GATEWAY_URL = "https://api.stripe.invalid/v1/charges"', "ce4d5a10"],
      ["BASE_DELAY_S = 0.25", "ca1f3c9e"],
      ["", "ce4d5a10"],
      ["", "ce4d5a10"],
      ["class GatewayClient:", "ce4d5a10"],
      ["    def __init__(self, session: requests.Session):", "ce4d5a10"],
      ["        self.session = session", "ce4d5a10"],
      ["", "ce4d5a10"],
      ["    def charge(self, attempt: PaymentAttempt) -> dict:", "ce4d5a10"],
      ['        headers = {"Idempotency-Key": attempt.idempotency_key}', "cb7d20f4"],
      ["        for n in range(MAX_RETRIES):", "ca1f3c9e"],
      ["            resp = self.session.post(GATEWAY_URL, json=attempt.payload, headers=headers)", "cb7d20f4"],
      ["            if resp.status_code < 500:", "ce4d5a10"],
      ["                return resp.json()", "ce4d5a10"],
      ["            time.sleep(random.uniform(0, BASE_DELAY_S * 2 ** n))", "ca1f3c9e"],
      ["        raise GatewayUnavailable(attempt.order_id)", "ce4d5a10"],
    ]),
  },
  {
    path: "src/auth/session_cache.py",
    lines: py([
      ["import time", "c7c2e8b3"],
      ["", "c7c2e8b3"],
      ["from .refresh import refresh_on_activity", "cd4e5f60"],
      ["", "c7c2e8b3"],
      ["SESSION_TTL_SECONDS = 900", "c9a8b7c1"],
      ["", "c7c2e8b3"],
      ["", "c7c2e8b3"],
      ["class SessionCache:", "c7c2e8b3"],
      ["    def __init__(self, store):", "c7c2e8b3"],
      ["        self._store = store", "c7c2e8b3"],
      ["", "c7c2e8b3"],
      ["    def get(self, token: str):", "c7c2e8b3"],
      ["        entry = self._store.get(token)", "c7c2e8b3"],
      ["        if entry is None:", "c7c2e8b3"],
      ["            return None", "c7c2e8b3"],
      ["        if time.time() - entry.last_seen > SESSION_TTL_SECONDS:", "c7c2e8b3"],
      ["            self._store.delete(token)", "c7c2e8b3"],
      ["            return None", "c7c2e8b3"],
      ["        return refresh_on_activity(entry)", "cd4e5f60"],
    ]),
  },
];

export const INVESTIGATIONS: Investigation[] = [
  {
    id: "retries",
    question: "Why are payment gateway retries capped at 3?",
    file: "src/payments/gateway_client.py",
    line: 8,
    summary:
      "Capped at 3 after incident PAY-412, where 10 retries without idempotency keys created duplicate charges. Raj proposed 3 in Slack and Dana kept it for the 8s checkout latency budget; PR #218 shipped it together with idempotency keys.",
    nodes: ["pay412", "thrA", "msgRaj", "msgDana", "pr218", "ca1f3c9e", "cb7d20f4", "ce4d5a10"],
    claims: [
      { id: "a1", status: "supported", afterStep: 4,
        text: "The cap was lowered from 10 to 3 in response to incident PAY-412.",
        cites: [{ node: "ca1f3c9e", quote: "PAY-412: retries amplified duplicate charges during the outage." }, { node: "pr218", quote: "Fixes PAY-412." }, { node: "pay412" }] },
      { id: "a2", status: "supported", afterStep: 4,
        text: "Retries were harmful because some 502s arrived after the charge had already succeeded upstream, so each retry created a new charge.",
        cites: [{ node: "pay412", quote: "Some 502s were returned AFTER the charge succeeded upstream, so every retry created a new charge." }] },
      { id: "a3", status: "supported", afterStep: 5,
        text: "The value 3 was chosen because it covered 99.2% of transient 502s, failing fast beyond that.",
        note: "Single source: one Slack message. The underlying log analysis is not in the graph.",
        cites: [{ node: "msgRaj", quote: "3 covers 99.2% of transient 502s in last quarter's logs" }] },
      { id: "a4", status: "supported", afterStep: 5,
        text: "3 was kept, even with idempotency keys, to stay inside the 8s checkout latency budget.",
        cites: [{ node: "msgDana", quote: "Keep 3 even after idempotency lands" }, { node: "pr218", quote: "Retry cap stays at 3 for the 8s checkout latency budget." }] },
      { id: "a5", status: "inferred", afterStep: 6,
        text: "Full-jitter backoff was likely added to avoid synchronized retry storms when the gateway recovers.",
        note: "No source states this rationale. PR #218 only mentions the change; 'jittered backoff' appears in Slack without a reason.",
        cites: [{ node: "pr218", quote: "full-jitter backoff" }, { node: "msgRaj", quote: "jittered backoff" }] },
      { id: "a6", status: "unknown", afterStep: 6,
        text: "Whether 3 is still the right number today.",
        note: "No data after 2026-03-06 in scope; no config or metrics source ingested.",
        cites: [] },
    ],
    gaps: [
      "The log analysis behind “99.2%” is not ingested (Slack message cites it, no link).",
      "No design doc or ADR found for the retry policy.",
      "Checkout latency budget (8s) is stated in chat only; no config or SLO source.",
    ],
    trace: [
      { kind: "understand", label: "Understand question", detail: "Anchor src/payments/gateway_client.py:8 · intent: rationale", ms: 320 },
      { kind: "plan", label: "Plan", detail: "blame → expand explicit links → read discussions → find gaps", ms: 540 },
      { kind: "tool", label: "search_path(“gateway_client”)", detail: "5 rows · 1 PR, 3 commits, 1 README PR", ms: 180 },
      { kind: "tool", label: "expand(PR #218)", detail: "4 rows · PAY-412, #payments-incident, 2 commits", ms: 210 },
      { kind: "tool", label: "expand(#payments-incident)", detail: "3 rows · 2 replies, PAY-412", ms: 190 },
      { kind: "gap", label: "Find gaps", detail: "3 gaps · 1 claim has only one source · 1 unsupported rationale", ms: 760 },
      { kind: "synthesize", label: "Synthesize", detail: "6 claims · 4 supported · 1 inferred · 1 unknown", ms: 900 },
    ],
    checks: [
      { label: "Idempotency key still sent on every charge", state: "holds", detail: "Line 18 unchanged since b7d20f4." },
      { label: "No later commits touch MAX_RETRIES", state: "holds", detail: "0 commits since 2026-03-03; #220 is a README typo." },
      { label: "8s checkout latency budget", state: "unknown", detail: "No config or SLO source ingested." },
    ],
    excluded: [
      { node: "pr220", reason: "Keyword match on “retries” only. README typo, no explicit link." },
      { node: "cc0ffee1", reason: "Same week, unrelated path, no explicit link." },
    ],
  },
  {
    id: "ttl",
    question: "Why is the session TTL 15 minutes?",
    file: "src/auth/session_cache.py",
    line: 5,
    summary:
      "15 minutes is a compliance requirement from audit finding SEC-77. It caused mid-checkout logouts, so instead of reverting, security added sliding refresh (PR #201): the idle limit stays at 15 minutes but active users no longer hit it.",
    nodes: ["sec77", "pr190", "c9a8b7c1", "thrB", "msgMira", "pr201", "cd4e5f60", "c7c2e8b3"],
    claims: [
      { id: "b1", status: "supported", afterStep: 3,
        text: "The TTL was set to 900s to satisfy the SEC-77 audit requirement (idle lifetime ≤ 15 min).",
        cites: [{ node: "sec77", quote: "Requirement: idle session lifetime <= 15 minutes." }, { node: "pr190", quote: "to satisfy the SEC-77 audit requirement" }, { node: "c9a8b7c1" }] },
      { id: "b2", status: "supported", afterStep: 4,
        text: "Support reported users being logged out mid-checkout and asked for a revert.",
        cites: [{ node: "thrB", quote: "lots of tickets about being logged out mid-checkout" }] },
      { id: "b3", status: "supported", afterStep: 4,
        text: "A revert was rejected because SEC-77 is a compliance item.",
        cites: [{ node: "msgMira", quote: "can't revert, SEC-77 is a compliance item" }] },
      { id: "b4", status: "supported", afterStep: 5,
        text: "Sliding refresh (PR #201) was added so active users never hit the idle limit; the 15 min TTL itself was kept.",
        cites: [{ node: "pr201", quote: "Keeps 15 min idle TTL from SEC-77 but refreshes on activity" }, { node: "msgMira", quote: "sliding refresh tokens" }] },
      { id: "b5", status: "inferred", afterStep: 5,
        text: "The Slack proposal is the direct origin of PR #201.",
        note: "PR #201 references the #support thread explicitly, but the link to Mira's specific message is inferred from matching wording.",
        cites: [{ node: "pr201", quote: "per #support discussion" }, { node: "msgMira" }] },
      { id: "b6", status: "unknown", afterStep: 5,
        text: "Why exactly 15 minutes rather than a shorter value.",
        note: "The audit report itself is not ingested; only the Jira summary is.",
        cites: [] },
    ],
    gaps: [
      "The external pen-test report behind SEC-77 is not in the graph.",
      "No record of alternatives considered (e.g. 10 min, step-up auth).",
      "Jira status of SEC-77 not ingested, so “still required” can't be verified.",
    ],
    trace: [
      { kind: "understand", label: "Understand question", detail: "Anchor src/auth/session_cache.py:5 · intent: rationale", ms: 300 },
      { kind: "plan", label: "Plan", detail: "blame → follow SEC-77 → read discussions → find later changes", ms: 480 },
      { kind: "tool", label: "search_text(“SESSION_TTL”)", detail: "3 rows · PR #190, PR #201, commit 9a8b7c1", ms: 170 },
      { kind: "tool", label: "expand(PR #190)", detail: "2 rows · SEC-77, commit 9a8b7c1", ms: 200 },
      { kind: "tool", label: "expand(SEC-77)", detail: "4 rows · #support thread + reply, PR #201", ms: 230 },
      { kind: "gap", label: "Find gaps", detail: "3 gaps · 1 inferred link · audit report missing", ms: 700 },
      { kind: "synthesize", label: "Synthesize", detail: "6 claims · 4 supported · 1 inferred · 1 unknown", ms: 880 },
    ],
    checks: [
      { label: "Sliding refresh still active", state: "holds", detail: "Line 19 unchanged since d4e5f60." },
      { label: "SEC-77 requirement still open", state: "unknown", detail: "Jira status not ingested." },
      { label: "Logout complaints after refresh shipped", state: "unknown", detail: "No #support activity ingested after 2026-02-05." },
    ],
    excluded: [],
  },
];

export const BY_ID = NODES;
export const KINDS: { kind: Kind; label: string; color: string }[] = [
  { kind: "issue", label: "Issue", color: "#fb923c" },
  { kind: "discussion", label: "Discussion", color: "#f472b6" },
  { kind: "pr", label: "Pull request", color: "#a78bfa" },
  { kind: "commit", label: "Commit", color: "#60a5fa" },
];
export const KIND_COLOR = Object.fromEntries(KINDS.map((k) => [k.kind, k.color])) as Record<Kind, string>;

/** Which investigation (if any) owns a blamed commit. */
export const investigationFor = (nodeId: string) => INVESTIGATIONS.find((i) => i.nodes.includes(nodeId));

/** Parent PR of a commit, via CONTAINS. Used to group blame stripes. */
export const prOf = (commitId: string) => EDGES.find((e) => e.rel === "CONTAINS" && e.to === commitId)?.from;

export const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
