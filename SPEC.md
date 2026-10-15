# Product specification — Engineering Memory

> Status: amended 2026-10-15 to cover the full MVP (ingestion → graph → agent → UI). Approved by the project owner in chat; recorded via Genesis.

## Problem

Why code is the way it is lives across GitHub (commits, PRs, reviews), Jira (issues) and Slack (threads). Engineers debugging or about to change code cannot cheaply find that rationale. This product ingests those sources into one evidence graph in Neo4j and lets an agent answer "why", "debug this" and "is it safe to change?" with cited evidence — and refuse when the evidence is not there.

## Users

- Engineers debugging a failure, or asking "why is this like this / can I change it?" before touching code.
- A single-user local workspace is the MVP deployment (tokens in environment; no OAuth, no multi-tenant).

## Functional requirements

Ingestion (built, unit + Neo4j integration tested):

- FR-1: Replaceable GitHub, Jira and Slack adapters with cursor/page progress; provider models do not leak past mappers.
- FR-2: Versioned source-neutral record envelope with canonical identity, times, content, references, provenance and raw payload.
- FR-3: Deterministic extraction of IDs, URLs, times, paths, diffs and explicit references, each with source locator and version.
- FR-4: Idempotent Neo4j upserts with stable IDs; edges carry source, observed time and provenance.
- FR-5: Native-shaped mock datasets replayable without credentials or network.
- FR-6: Bounded backfill and cursor-based incremental replay without duplicates.
- FR-7: Semantic extraction stays disabled by default.
- FR-8: Structured, secret-free ingestion run summaries.

Platform (new):

- FR-9: Explicit text references. Jira keys of configured projects, GitHub PR/commit URLs, `#N` (inside GitHub records only) and Slack permalinks found in titles/bodies/messages become typed `REFERENCES` edges with `origin=text` and a locator; structural edges carry `origin=structural`. No fuzzy or semantic matching.
- FR-10: Workspace sync. A `workspace.json` names GitHub repos, Jira projects and Slack channels; `sync` ingests them through the real clients (PR→commits `CONTAINS` edges, Jira project search, Slack channel history + replies). `--demo` replays a linked demo workspace through the same clients and mappers with fake transports.
- FR-11: Agent harness. The LLM never writes Cypher. It selects from fixed, parameterized, read-only tools (text search, file history, neighbours, evidence chain, fetch); arguments are validated, ids must come from earlier evidence, results are row- and time-capped, and every template is EXPLAIN-checked against the live database.
- FR-12: LLM providers Azure Foundry and Sarvam AI behind one interface, selected by configuration or per request.
- FR-13: Answer integrity. Every cited URL must belong to retrieved evidence; unsupported citations are removed and confidence is capped; insufficient evidence yields an explicit "not established" answer rather than a guess.
- FR-14: Modes: `why`, `debug` (paths/keys extracted deterministically from pasted errors seed retrieval) and `change` (what constraints and decisions guard this code).
- FR-15: API and web UI. The UI is the owner's Next.js "why workbench" (`web/`) wired to the real backend per `docs/workbench-api.md`: connections dialog (real workspace config, sync, demo), code pane with blame, ask box and line-click investigations, live agent trace, claim-level answer, gaps, "still valid?" checks, excluded evidence and the evidence graph. No mock data remains.
- FR-16: Claim-level investigations. An answer is a set of claims, each `supported` (a source states it), `inferred` (the agent's reasoning, flagged) or `unknown`, with citations whose quotes are verified verbatim against the cited node's text in code; unverifiable citations are dropped and unsupported claims are downgraded. Excluded evidence carries a deterministic reason; "still valid?" checks are deterministic graph facts. Investigations are stored and re-openable.
- FR-17: Blame from evidence. Per-line blame for a file is computed by replaying the ingested commit patches (oldest to newest); when history is missing or a patch does not apply the result is marked incomplete with a note and nothing is guessed.

## Non-functional requirements

- NFR-1: Core contract and writer do not depend on provider SDKs.
- NFR-2: Demo and tests need no provider credentials or external network (LLM calls excepted).
- NFR-3: Graph writes are idempotent; replay yields identical logical graphs.
- NFR-4: Secrets only via environment; never logged, committed or returned by the API.
- NFR-5: Neo4j is configurable by URI/database/user/password; the agent works with a read-only user.

## Non-goals

- OAuth onboarding, multi-tenant deployment, queues, webhooks/streaming ingestion.
- Vector search, embeddings, semantic or causal link inference; inferred facts are never stored as edges.
- Hosts other than GitHub, Jira Cloud, Slack.

## Acceptance criteria

- AC-1: Fixture payloads replay into a disposable Neo4j with no external services.
- AC-2: Demo graph contains commit → PR → Jira issue → Slack thread chains, each edge traceable to a source locator.
- AC-3: Re-running sync/demo twice leaves node and edge counts unchanged.
- AC-4: Run summaries expose cursors, counts, versions and failures without secrets.
- AC-5: Semantic extraction is off.
- AC-6: Against the demo workspace, "Why are gateway retries capped at 3?" returns an answer citing the PR, the Jira issue and the Slack discussion that are in the graph.
- AC-7: A question with no evidence in the graph is answered "not established" with low confidence and no citations.
- AC-8: A citation not present in retrieved evidence never reaches the user.
- AC-9: The same question works with either configured provider (Azure or Sarvam) without code changes.
- AC-10: From a clean checkout, `uv sync`, `docker compose up -d`, `uv run hackfront demo`, `uv run hackfront serve` and `npm run dev` in `web/` yield a working UI.
- AC-11: In the UI, clicking the `MAX_RETRIES = 3` line of the demo `gateway_client.py` opens an investigation whose supported claims cite the Jira issue, PR and Slack discussion with verified quotes.
- AC-12: A fabricated citation id or non-verbatim quote returned by a model never appears as a supported citation.

## Risks

- Source payloads contain private content: demo data is synthetic; live use is local-only and token-scoped read-only.
- A graph can imply causality the source never asserted: only explicit links become edges; the agent must say when a link is time-adjacency only.
- LLM output can be malformed or unsupported: schema validation, one repair round trip, citation verification.
- Provider API drift (Sarvam models/endpoints): provider settings are configuration, not code.

## Constraints

- Python managed with uv (single project at repo root, `src/hackfront`); Neo4j via the official driver; LangGraph for the agent flow; FastAPI for the API; the UI is the Next.js app in `web/` (dev server proxies `/api/*` to FastAPI).
- LLM providers use OpenAI-compatible chat endpoints: Azure Foundry (`/openai/v1/`) and Sarvam (`https://api.sarvam.ai/v1/`, `api-subscription-key` header).
- A dedicated Neo4j runs via `docker-compose.yml` on ports 7688/7475; other local Neo4j instances are never touched.

## Open questions

- Which Sarvam model (`sarvam-30b` vs `sarvam-105b`) gives best structured-JSON reliability; configurable via `LLM_MODEL`, evaluated against the regression questions.
- Live-source scopes (GitHub fine-grained read token, Jira API token, Slack bot with `channels:history`) are exercised only with real credentials supplied by the owner.
