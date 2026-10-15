# Engineering Memory: why workbench

Next.js UI for "why is this code the way it is?", backed by the FastAPI service in `src/hackfront/api`
(contract: `docs/workbench-api.md`, v2). Every `/api/*` request is proxied by `next.config.ts` to `HACKFRONT_API`
(default `http://127.0.0.1:8000`), so the browser stays same-origin.

```bash
# repo root: backend on :8000 (needs Neo4j, see .env.example)
uv run hackfront serve --port 8000
# web/
npm install
npm run dev   # http://localhost:3000
```

Everything is per workspace: connections, credentials, AI model, sync job and graph scope all live under `/api/w/{ws}/...`.

## Onboarding flow

1. `/` lists workspaces. **Create workspace**, or **Try the demo workspace** (creates "Acme Demo" and starts ingesting automatically).
2. `/w/[ws]/setup` is one checklist with live status per step:
   1. **Connect sources**: GitHub (token + owner), Jira (site, email, API token), Slack (bot token + workspace subdomain). *Save & test* stores the credentials and checks them; then pick what to ingest from the discovered list (or add by id) and *Save selection*.
   2. **AI model**: Azure (endpoint + key) or Sarvam (key), optional model; *Save & test* runs one tiny completion.
   3. **Ingest**: Standard (20 pages per stream) or Deep history (100). Progress is polled every second from `GET /sync`; it is server-side, so a reload resumes. Incomplete streams offer *Sync deeper*.
   4. **Ask**: *Open workbench* once data and the AI model exist (demo workspaces add suggested questions).
3. The same cards live in the workbench under **Connections** (top bar switcher), together with rename and delete.

Credential inputs are write-only: values are sent once and never read back or stored in the browser; saved ones show the API's masked hint with a Replace action.
A banner under the top bar shows a running sync from any page.

## Workbench

| Where | What |
|---|---|
| `/w/[ws]` | Redirects to the first indexed repo, or to `/w/[ws]/setup` when nothing is ingested |
| `/w/[ws]/[repo]/f/[...path]` | Code with blame, evidence drawer (timeline / graph / source), answer on the right |
| `/w/[ws]/[repo]/why/[id]` | A stored investigation |
| top bar | Workspace switcher, repo / file crumb, search (`Ctrl/⌘ K`), theme |

Click a line whose commit has recorded links to ask why it is that way; or type a question in the Answer pane.
Steps stream in live; claims, gaps and checks appear when the investigation finishes and is stored.
Workbench keys: `1`/`2` timeline/graph · `j`/`k` step evidence · `r` replay · `Esc` clear.

Code map: `lib/api.ts` (`wsApi` helpers + SSE reader), `lib/data.tsx` (`DataProvider` keyed by workspace: workbench, graph, investigations, sync polling),
`lib/types.ts` (contract types), `components/Setup.tsx` (checklist), `Integrations.tsx` (source cards, pickers, AI model), `SyncPanel.tsx`, `ConfigDialog.tsx`.
