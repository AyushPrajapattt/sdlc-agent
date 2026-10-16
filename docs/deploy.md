# Deploy (Vercel UI + container API + Neo4j Aura)

The API cannot run on Vercel's serverless functions: it runs sync jobs in background threads, streams answers for minutes,
and stores workspaces and keys on disk. So: **UI on Vercel (already done), API in a container with a disk, DB on Neo4j Aura.**

## 1. Database: Neo4j Aura Free (2 min)
console.neo4j.io → New instance → **Free**. Save the connection URI (`neo4j+s://xxxx.databases.neo4j.io`), username and
password it shows once. The database name is usually `neo4j` (check the instance page).

## 2. API: Render Blueprint (3 clicks)
Push this repo to GitHub, then Render → **New → Blueprint** → pick the repo (it reads `render.yaml` + `Dockerfile`).
Enter `NEO4J_URI`, `NEO4J_USERNAME`, `NEO4J_PASSWORD` (and `NEO4J_DATABASE` if not `neo4j`). Deploy.
Render generates `HACKFRONT_ACCESS_TOKEN` (Environment tab): copy it. The API URL looks like `https://hackfront-api.onrender.com`;
`https://<url>/health` should return `{"ok":true}`.
Notes: the 1 GB disk (`/data`) holds workspaces, saved keys and investigations and needs a paid instance; keep one instance only.
Railway or Fly.io work the same way with this Dockerfile (mount a volume at `/data`, set the same env vars).

## 3. Vercel: two environment variables, then redeploy
Project → Settings → Environment Variables (Root Directory `web`):
- `HACKFRONT_API` = the API URL from step 2
- `HACKFRONT_API_TOKEN` = the `HACKFRONT_ACCESS_TOKEN` value

The browser only talks to your Vercel domain; `app/api/[...path]/route.ts` forwards to the API and adds the token server-side.

## 4. Use it
Open the Vercel URL → **Try the demo workspace**, or create a workspace and enter your GitHub/Jira/Slack/AI keys in the UI.

## Read this before sharing the URL
The Vercel app has **no login**: anyone who opens it can use your workspaces, read ingested data, start syncs and spend your
AI-model credits (saved keys are never shown, but they are usable). Turn on Vercel **Deployment Protection**, or ask for a
shared-password gate to be added, before you share the link. Saved keys are stored unencrypted on the API's disk.
