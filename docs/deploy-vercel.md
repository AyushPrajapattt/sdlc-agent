# Deploy everything on Vercel (API + UI) with Neo4j Aura, free

Two Vercel projects from this one repo, plus a free Neo4j Aura database. The API is a normal FastAPI app; on Vercel it runs as a
Python Function (`src/main.py` is the entrypoint, `vercel.json` raises its time limit to 300 s).

## 1. Database: Neo4j Aura Free
console.neo4j.io → New instance → Free. Keep the URI (`neo4j+s://…`), username, password, database name (usually `neo4j`).

## 2. API project (new Vercel project)
Import the repo, **Root Directory: the repository root** (leave empty). Vercel detects the FastAPI app from `src/main.py` and installs the
dependencies from `pyproject.toml`; `.vercelignore` keeps tests and docs out of the bundle (never list `web` there: for the UI project, whose Root Directory is `web`, Vercel falls back to this root file and it would strip the app). Environment variables:

| Variable | Value |
|---|---|
| `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD`, `NEO4J_DATABASE` | from Aura |
| `HACKFRONT_SECRET_KEY` | any long random string; encrypts API keys saved in the UI. Keep it |
| `HACKFRONT_ACCESS_TOKEN` | any long random string; the UI proxy must send it |

You do **not** set `HACKFRONT_STATE` or `HACKFRONT_SYNC`: on Vercel (`VERCEL` is set) they default to `neo4j` and `inline`.
Optional: `HACKFRONT_SYNC_BUDGET` (seconds, default 240). Check `https://<api>.vercel.app/health` → `{"ok":true}`.
Leave Deployment Protection **off** on this project: the UI's server calls it directly and it is already guarded by the access token. If
the UI shows an HTML 401/403 from Vercel instead of JSON, that setting is the cause.

## 3. UI project (the one you already have, Root Directory `web`)
Add `HACKFRONT_API` = the API project URL and `HACKFRONT_API_TOKEN` = the same value as `HACKFRONT_ACCESS_TOKEN`, then redeploy. Put
Deployment Protection (Vercel Authentication, free on Hobby) on **this** project if you do not want the public to use the app.

## How it behaves on Vercel
- **State** lives in Neo4j (workspaces, encrypted keys, investigations, sync status): no disk is used (Vercel's is read-only).
- **Sync runs inside the request.** *Start ingestion* keeps one request open and the page shows live progress by polling the status that
  the sync saves (with a heartbeat, so any instance can tell a running job from a dead one and a second start is refused).
  The sync stops cleanly after the time budget (240 s); streams it did not finish are marked *incomplete* ("Stopped at the time
  limit"). Keep the tab open while it runs.
- **Investigations** stream within one request and fit the 300 s limit unless the model is very slow.

## Limits to know (free plan)
- A first ingest of a **large** repo will not finish within 240 s. There is no incremental cursor yet, so running it again starts from the
  newest page again. Demo workspaces and small repos finish; for big repos use the Render setup in `deploy.md` (no time cap) until
  incremental sync exists.
- Hobby includes 4 CPU-hours and 1,000,000 invocations a month; beyond that Vercel pauses the project for 30 days. Hobby is for personal,
  non-commercial use.
- Cold starts add a few seconds to the first request after idle (Python imports).

## What was and was not verified
Verified locally by running the same entrypoint (`uvicorn main:app --app-dir src`) in a clean Python 3.12 environment with only the
declared dependencies and the project **not** installed, `VERCEL=1`, and an empty read-only-style home: defaults picked neo4j + inline,
the token guard returned 401 without a token, a demo workspace was created and synced in one request (26 artifacts, 50 links) and no
file was written. Tests cover the heartbeat across "instances", duplicate-start refusal, the time budget and the shared connection.
**Not verified** (needs a real Vercel deploy): the function bundle size and install, the Python version Vercel picks, cold-start time,
SSE streaming of investigations through Vercel's proxy, and how Vercel schedules concurrent requests across instances.
