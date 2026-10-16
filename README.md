# Engineering Memory

Connect GitHub, Jira and Slack into one **evidence graph**, then ask *why is this code like this?*, *debug this error*, or *is it safe to change this?* and get an answer where every claim links to its source — or an honest "not established".

```mermaid
flowchart LR
  GH[GitHub] & JI[Jira] & SL[Slack] --> ING[Ingestion<br/>explicit links only]
  ING --> NEO[(Neo4j)]
  NEO <--> AG[Agent harness<br/>Azure / Sarvam]
  AG --> UI[Web UI]
```

## What is different

- **Edges are evidence, not guesses.** A link exists only if a source stated it (PR contains commit, reply-to, or an explicit `PAY-412` / PR URL / Slack permalink in text). Each edge records its `origin` and a source locator. No keyword or timing inference.
- **The LLM does not get free rein over the database.** It picks from validated, read-only, capped graph tools; ids must come from evidence already seen; a guarded text2cypher path exists for complex questions and is only used to *find* ids, which are then re-read through trusted templates.
- **Citations are verified in code.** A cited URL that was not retrieved is dropped and confidence is capped. "Not established" is a first-class answer.
- **Demo and live share one path.** Demo data is native-shaped API payloads served to the real clients and mappers.

More: [docs/architecture.md](docs/architecture.md) · scope and acceptance criteria: [SPEC.md](SPEC.md)

## Run it

```bash
uv sync
cp .env.example .env          # Neo4j settings only; everything else is entered in the UI
docker compose up -d          # Neo4j on bolt://localhost:7688 (+ throwaway test DBs on 7689/7690)
uv run hackfront serve        # API on http://127.0.0.1:8000 (no UI of its own)
cd web && npm ci && npm run dev   # the workbench UI on http://localhost:3000 (proxies /api to :8000)
```

If port 3000 is taken, run the UI on another port (`npm run dev -- --port 3100`); any localhost port works. To open the UI from another address (e.g. a LAN IP), start the API with `HACKFRONT_ORIGINS=http://<that-address>:<port>`.

## Onboarding (all in the UI)

Open http://localhost:3000. A **workspace** owns its connections, credentials, AI model and data view.

- **Demo in one click:** *Try the demo workspace* creates "Acme Demo", ingests synthetic GitHub, Jira and Slack data through the real pipeline with live progress, then open a file and **click the `MAX_RETRIES = 3` line**. Each claim is marked supported / inferred / unknown with quotes verified against the sources. Only an AI model key is needed.
- **Your own sources:** *Create workspace*, then on the setup page: enter credentials per source and **Save & test**, pick repos, Jira projects and Slack channels from the discovered lists, add the AI model key, **Start ingestion** and watch it live, then **Open workbench**.

| Source | What to enter |
|---|---|
| GitHub | fine-grained read-only token (Contents, Pull requests, Issues, Metadata) + owner |
| Jira Cloud | site `https://<you>.atlassian.net`, email, API token (id.atlassian.com) |
| Slack | bot token with `channels:history`, `groups:history`, `channels:read`, `users:read`; invite the bot to the channels; your Slack subdomain |
| AI model | Azure Foundry (endpoint + key) or Sarvam (key); optional model name |

Keys are stored per workspace in `.hackfront/workspaces/<id>/secrets.json` on this machine, are write-only (the UI and API show only `••••1234`), and environment variables (`GITHUB_TOKEN`, `SARVAM_API_KEY`, ...) work as a fallback. CLI equivalents: `uv run hackfront demo`, `sync --workspace <id> [--deep]`, `workspaces`, `ask "..." --workspace <id>`.

Demo questions: *Why are gateway retries capped at 3?* · *Why is the session TTL 15 minutes?*; and one it cannot answer (*Why did we choose Redis for the session cache?*), where the agent should say "not established".

## Test

```bash
uv run pytest tests/ingest tests/agent tests/api -q   # needs `docker compose up -d` (test Neo4j on 7689)
uv run pytest tests/e2e -q                             # real LLM calls; skips providers without keys
```

Neo4j tests wipe `Artifact` nodes in the **test** database only.

## Layout

`src/hackfront/ingest` contracts, sources (github/jira/slack), extraction (deterministic + text links), Neo4j storage, sync, demo data · `src/hackfront/agent` providers, harness, flow, verification · `src/hackfront/api` FastAPI · `web/` Next.js workbench UI · `research/` background papers.

## Known limits

- Local single-user tool: the API has no login, credentials sit in a local file (not encrypted), and it binds to 127.0.0.1; do not expose it. Run the agent with a read-only Neo4j user in any shared setup.
- Sync is a bounded full backfill (20 pages per stream, 100 with Deep history) through idempotent writes, not an incremental cursor; the UI flags incomplete streams. Text-derived edges are rebuilt from current text on every write; deleted source records are not removed from the graph.
- Real-LLM behaviour (Azure, Sarvam) is covered by `tests/e2e` and needs your keys; unit tests use scripted models.
