# Engineering Memory: why workbench

Next.js UI for "why is this code the way it is?", backed by the FastAPI service in `src/hackfront/api`
(contract: `docs/workbench-api.md`). Every `/api/*` request is proxied by `next.config.ts` to `HACKFRONT_API`
(default `http://127.0.0.1:8000`), so the browser stays same-origin.

```bash
# repo root: backend on :8000 (needs Neo4j, see .env.example)
uv run hackfront serve --port 8000
# web/
npm install
npm run dev   # http://localhost:3000
```

| Where | What |
|---|---|
| `/` | The local workspace. **Connections** edits `workspace.json` (repos, Jira projects, Slack channels), syncs, loads demo data |
| top bar | Workspace switcher, repo / file crumb, search (`Ctrl/⌘ K`), theme |
| `/w/local` | Left pane lists the connected and indexed repos |
| `/w/local/[repo]/f/[...path]` | Code with blame, evidence drawer (timeline / graph / source), answer on the right |
| `/w/local/[repo]/why/[id]` | A stored investigation (`GET /api/investigations/{id}`) |

Click a line whose commit has recorded links to ask why it is that way; or type a question in the Answer pane.
Steps stream in live; claims, gaps and checks appear when the investigation finishes and is stored.
Tokens are read by the server from its environment and are never entered here.
Disconnect a Jira project or Slack channel and its artifacts drop out of the evidence; claims citing them show a lock.
Workbench keys: `1`/`2` timeline/graph · `j`/`k` step evidence · `r` replay · `Esc` clear.

Data layer: `lib/api.ts` (fetch + SSE reader), `lib/data.tsx` (`DataProvider`, loads workbench / graph / investigations), `lib/types.ts` (contract types).
