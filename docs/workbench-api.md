# Workbench API contract v2 (Next.js UI <-> FastAPI)

The UI is `web/` (Next.js 16, the owner's "why workbench"). FastAPI serves JSON/SSE only; dev: API :8000, Next
proxies `/api/*`. Everything user-visible is **per workspace**: `/api/w/{ws}/...`. Errors are `{"detail": "<safe message>"}`
with 4xx/5xx; never stack traces or secret values. Security is deliberately minimal (local single-user tool):
secrets are write-only through the API, stored in `HOME/.hackfront/workspaces/<ws>/secrets.json`, never returned
(only a masked hint). Storage and helpers: `hackfront.config` (workspaces, secrets, scopes, names).

## Workspace model

A workspace = a name + targets (GitHub owner/repos, Jira site/projects, Slack workspace subdomain/channels) +
credentials (secrets) + a demo flag. `demo: true` workspaces ingest the synthetic demo through the same clients and
need no source credentials. Data isolation: each ingested artifact stores `scope` (repo `owner/repo`, Jira project key,
Slack channel id); a workspace sees only artifacts whose scope is one of its connected targets (`config.scopes(ws)`,
`api.mapping.flat_scopes`). Two workspaces connecting the same repo share its nodes (source evidence), nothing else.

## Shapes (unchanged from v1 unless noted)

```ts
Node   { id, cid, kind: "issue"|"discussion"|"pr"|"commit", source: "jira"|"github"|"slack", ref, title, text, author,
         time, url, paths?: string[], scope }            // built ONLY by hackfront.api.mapping (names applied)
Edge   { from, to, rel, origin: "structural"|"text", locator }
Cite, Claim, Step, Check, Investigation, Graph          // exactly as docs/web/lib/types.ts
WorkspaceRow { slug, name, demo, connected: {repos:number, jira:number, slack:number}, last_sync?: {state, finished_at} }
SecretState  { set: boolean, source: "workspace"|"env"|null, value?: string /*non-secret keys only*/, hint?: string /*masked*/ }
SyncStream   { stream: string, status: "running"|"done"|"incomplete"|"failed", pages: number, fetched: number,
               persisted: number, errors: {stage,type,message}[] }
SyncStatus   { state: "idle"|"running"|"done"|"failed", mode: "standard"|"deep", started_at?, finished_at?,
               streams: SyncStream[], totals: {fetched, persisted, errors}, graph?: {artifacts, edges, stubs},
               complete: boolean, error?: string }
Resource     { id: string, name: string, private?: boolean, detail?: string }
```

Secret keys (`config.SECRETS`): `github_token jira_email jira_token slack_token azure_endpoint azure_key sarvam_key llm_provider llm_model`.
Non-secret keys (`jira_email azure_endpoint llm_provider llm_model`) return `value`; others return only `hint`.

## Endpoints

| Method + path | Body | Response |
|---|---|---|
| `GET /api/workspaces` | | `WorkspaceRow[]` |
| `POST /api/workspaces` | `{name, demo?: boolean}` | `{slug, name, demo}` 201. `demo:true` also fills targets/names with the demo workspace (`ingest.demo.DEMO_WORKSPACE`). |
| `DELETE /api/workspaces/{ws}` | | `{ok:true}` (config, secrets, stored investigations; graph data stays) |
| `GET /api/w/{ws}/workbench` | | `{workspace:{slug,name,demo}, connected:{repos[],jira[],slack[]}, catalog:{repos[],jira[],slack[]}, indexed_repos:string[], neo4j:{ok,counts?}, integrations:{github,jira,slack,llm: {configured:boolean, secrets:{[key]:SecretState}, targets?:number}}, providers:[{name,model,configured}], names:{channels,users}}` ; `catalog` = connected plus every scope of that workspace present in the graph; `indexed_repos` = connected repos with ingested commits. 404 unknown workspace. |
| `PUT /api/w/{ws}/workspace` | targets: `{name?, github:{owner,repos[]}, jira:{site,projects[]}, slack:{workspace,channels[]}}` | clean workspace (`channel_names`/`users` are server-managed and preserved) ; 422 safe validation message |
| `PUT /api/w/{ws}/secrets` | any subset of secret keys; `""` clears | `{[key]:SecretState}` (write-only; values never echoed back for secret keys) |
| `POST /api/w/{ws}/integrations/{github\|jira\|slack\|llm}/test` | | `{ok:boolean, detail:string, account?:string}` using the stored credentials (llm: one tiny completion with the workspace's provider). 200 even when `ok=false` (bad token) with a safe `detail`. |
| `GET /api/w/{ws}/integrations/{github\|jira\|slack}/resources` | | `{resources: Resource[]}` discovery for pickers: github repos of `github.owner` (user or org; else the token's repos); jira projects; slack channels (`conversations.list`, public + private the bot can see). Demo workspaces return the demo catalog. 4xx/5xx safe message when credentials are missing/invalid. |
| `POST /api/w/{ws}/sync` | `{mode?: "standard"\|"deep"}` | 202 `SyncStatus` (job started in a background thread). 409 if one is running, 422 if the workspace has no targets. `standard` = 20 pages per stream, `deep` = 100. |
| `GET /api/w/{ws}/sync` | | `SyncStatus` (poll ~1 s while running; persisted to `sync.json` so the last result survives a restart) |
| `GET /api/w/{ws}/graph` | | `Graph` of non-stub artifacts in the workspace scopes (cap 3000 nodes), names applied |
| `GET /api/w/{ws}/repo/{owner}/{repo}/files` | | `{files: string[]}` (404 unless the repo is a connected target of the workspace) |
| `GET /api/w/{ws}/repo/{owner}/{repo}/file?path=` | | `{path, lines:[{text, blame}], complete, note?}` (as v1) |
| `POST /api/w/{ws}/investigate` | `{question, mode?, provider?, model?, file?, line?, repo?}` | SSE `trace`/`investigation`/`error` as v1. Uses the workspace's LLM credentials and ONLY its scopes. |
| `GET /api/w/{ws}/investigations`, `GET /api/w/{ws}/investigations/{id}` | | as v1, stored under the workspace dir |

Removed (v1, single workspace): `/api/status`, `/api/workspace`, `/api/sync`, `/api/demo`, `/api/ask`, `/api/workbench`,
`/api/graph`, `/api/repo/...`, `/api/investigate`, `/api/investigations...`.

## Sync semantics

Background job per workspace (`ingest.sync.start_sync`, `sync_status`). Streams appear as they start; each reports pages,
fetched, persisted and errors live (updated after every page). A stream that hits the page bound is `incomplete`; any
error makes it `incomplete` or `failed`; `complete` is true only when every stream is `done`. Slack sync also learns
channel names and user display names (best effort, needs `channels:read`/`users:read`) into the workspace
`slack.channel_names`/`slack.users`. Every ingested artifact gets `scope` written by the Neo4j writer.
Credentials come from `config.get_secret(ws, key)` (workspace store, then env); demo workspaces use demo clients.

## Agent isolation

`agent.run(..., scopes: list[str] | None, workspace: str | None)`; every harness template restricts returned artifacts to
`a.scope IN $scopes` (traversal may pass through other nodes but only in-scope non-stub nodes are returned or cited).
LLM credentials resolve through `agent.llm.set_workspace(slug)` (contextvar; set it inside the worker thread that runs the
investigation); `providers(workspace)` reports per-workspace `configured`.

## Ownership (parallel workstreams; do not edit outside your files)

- MVP-WS (platform API): `src/hackfront/api/workspaces.py`, `src/hackfront/ingest/sources/{github,jira,slack}/client.py`+`adapter.py` (discovery/test methods only), `src/hackfront/agent/llm.py`, `tests/api/test_workspaces.py`, `tests/api/test_api.py` (rewrite: keep origin/jira-host tests, delete the rest), `tests/ingest/unit/test_discovery.py`.
- MVP-SYNC: `src/hackfront/ingest/sync.py`, `src/hackfront/ingest/storage/neo4j/writer.py`, `src/hackfront/ingest/demo/**`, `src/hackfront/api/sync.py`, `src/hackfront/cli.py`, `tests/ingest/**` (sync/writer/demo tests).
- MVP-SCOPE: `src/hackfront/agent/**` except `llm.py`, `src/hackfront/api/investigate.py`, `src/hackfront/api/workbench.py`, `tests/agent/**`, `tests/api/test_investigate.py`, `tests/api/test_workbench.py`.
- MVP-WEB2: `web/**`.
- Lead-owned: `config.py`, `api/mapping.py`, `api/app.py`, `docs/`, `SPEC.md`, `README.md`.
