# Deploy for free (Vercel UI + container API + Neo4j Aura)

**State lives in Neo4j.** With `HACKFRONT_STATE=neo4j` the API keeps workspaces, saved API keys (encrypted), stored
investigations and sync status in the same database as the evidence graph, so the API container needs no disk and a restart or
idle sleep loses nothing. (Locally the default stays `HACKFRONT_STATE=file`.) Free hosting is therefore:
**UI on Vercel (already done), API on a free container host, DB on Neo4j Aura Free.**

The API can also run on Vercel itself (everything on Vercel + Aura): see [deploy-vercel.md](deploy-vercel.md). It works for the demo and small
repos; the 300 s request cap on the free plan means a first ingest of a large repo cannot finish there, which is why this Render
setup (no time cap) stays the recommendation for big repos.

## 1. Database: Neo4j Aura Free (2 min)
console.neo4j.io → New instance → **Free**. Save the connection URI (`neo4j+s://xxxx.databases.neo4j.io`), username and password
it shows once. The database name is usually `neo4j` (check the instance page). Check Aura's current free-tier limits and its
inactivity policy; an instance that is paused for inactivity must be resumed from the console.

## 2. API: Render Blueprint (free plan, 3 clicks)
Push this repo to GitHub, then Render → **New → Blueprint** → pick the repo (it reads `render.yaml` + `Dockerfile`). Enter
`NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` (and `NEO4J_DATABASE` if not `neo4j`). Deploy. Render generates two secrets
(Environment tab):
- `HACKFRONT_ACCESS_TOKEN`: copy it for Vercel.
- `HACKFRONT_SECRET_KEY`: encrypts the API keys you save in the UI. **Keep it.** Changing it makes saved keys unreadable (they must be
  entered again). Without it the API refuses to save keys.

`https://<service>.onrender.com/health` should return `{"ok":true}`. On the free plan the service sleeps after 15 idle minutes and
takes about a minute to wake; it must stay a single instance. Any container host works the same way with this Dockerfile (Cloud Run,
Railway, Fly): set the same env vars, no volume needed.

## 3. Vercel: two environment variables, then redeploy
Project → Settings → Environment Variables (Root Directory `web`):
- `HACKFRONT_API` = the API URL from step 2
- `HACKFRONT_API_TOKEN` = the `HACKFRONT_ACCESS_TOKEN` value

The browser only talks to your Vercel domain; `app/api/[...path]/route.ts` forwards to the API and adds the token server-side.

## 4. Use it
Open the Vercel URL → **Try the demo workspace**, or create a workspace and enter your GitHub/Jira/Slack/AI keys in the UI. The AI
model can also come from API environment variables (`AZURE_FOUNDRY_*`, `SARVAM_API_KEY`) if you prefer not to save it in the UI.

## Moving your existing local workspaces to Neo4j
With the same `NEO4J_*` in `.env` and a `HACKFRONT_SECRET_KEY` of your choice: `uv run hackfront migrate-state` copies every local
workspace, its saved keys (re-encrypted), stored investigations and last sync into Neo4j. Existing ones are skipped unless you pass
`--overwrite`. Use the same `HACKFRONT_SECRET_KEY` on the host.

## Read this before sharing the URL
The Vercel app has **no login**: anyone who opens it can use your workspaces, read ingested data, start syncs and spend your
AI-model credits (saved keys are never shown, but they are usable). On Vercel Hobby you can turn on Vercel Authentication (free; only
people on your Vercel team can view) and use shareable links for guests; password protection is a paid feature. Or ask for a
shared-password gate. Saved keys are encrypted with `HACKFRONT_SECRET_KEY`, but anyone with the database credentials plus that key
can read them.

## The API on Vercel instead
See [deploy-vercel.md](deploy-vercel.md): state is in Neo4j, sync runs inside the request with a 240 s budget, and a heartbeat lets any
instance report or refuse a sync. A first ingest of a large repo still needs incremental/chunked sync to complete there.
