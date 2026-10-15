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
- FR-15: API and web UI: source status and workspace form, sync/demo actions, ask box with mode and provider, live agent trace, cited answer, and the evidence subgraph used.

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
- AC-10: From a clean checkout, `uv sync`, `docker compose up -d`, `uv run hackfront demo`, `uv run hackfront serve` yields a working UI.

## Risks

- Source payloads contain private content: demo data is synthetic; live use is local-only and token-scoped read-only.
- A graph can imply causality the source never asserted: only explicit links become edges; the agent must say when a link is time-adjacency only.
- LLM output can be malformed or unsupported: schema validation, one repair round trip, citation verification.
- Provider API drift (Sarvam models/endpoints): provider settings are configuration, not code.

## Constraints

- Python managed with uv (single project at repo root, `src/hackfront`); Neo4j via the official driver; LangGraph for the agent flow; FastAPI for the API; the UI is static files served by the API (no JS build step).
- LLM providers use OpenAI-compatible chat endpoints: Azure Foundry (`/openai/v1/`) and Sarvam (`https://api.sarvam.ai/v1/`, `api-subscription-key` header).
- A dedicated Neo4j runs via `docker-compose.yml` on ports 7688/7475; other local Neo4j instances are never touched.

## Open questions

- Which Sarvam model (`sarvam-30b` vs `sarvam-105b`) gives best structured-JSON reliability; configurable via `LLM_MODEL`, evaluated against the regression questions.
- Live-source scopes (GitHub fine-grained read token, Jira API token, Slack bot with `channels:history`) are exercised only with real credentials supplied by the owner.
