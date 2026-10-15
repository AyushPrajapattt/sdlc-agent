# Engineering Memory — workspace mock

Next.js mock of an evidence workbench for "why is this code the way it is?". All data is static:
`lib/data.ts` (artifacts, code, blame, claims, trace; shaped like `agent/mock_graph.py`), `lib/workspaces.ts` (workspaces, connectable repos/Jira/Slack).

```bash
npm install
npm run dev   # http://localhost:3000
```

| Where | What |
|---|---|
| `/` | Workspaces. **Connections** picks repos, Jira projects, Slack channels per workspace (saved in localStorage) |
| top bar | Workspace switcher, repo / file crumb, search (`Ctrl/⌘ K`), theme |
| `/w/[ws]` | Left pane lists the workspace's repos; picking one focuses it (file tree only) |
| `/w/[ws]/[repo]/f/[...path]` | Code with blame, evidence drawer (timeline / graph / source), answer on the right |
| `/w/[ws]/[repo]/why/[id]` | Same workbench opened on a question |

Disconnect a Jira project or Slack channel and its artifacts drop out of the evidence; claims citing them show a lock.
Workbench keys: `1`/`2` timeline/graph · `j`/`k` step evidence · `r` replay · `Esc` clear.
To wire the real agent, replace the exports of `lib/data.ts` with fetches; the UI only reads those types.
