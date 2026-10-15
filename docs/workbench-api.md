# Workbench API contract (Next.js UI <-> FastAPI)

The UI is `web/` (Next.js 16, the owner's "why workbench"). Its types are `web/lib/data.ts`; this file is the
binding contract for the real backend. Dev: FastAPI on :8000, Next on :3000 with `rewrites` proxying `/api/*`.
All shapes are JSON. Errors: `{"detail": "<safe message>"}` with a 4xx/5xx status; never stack traces or secrets.

## Shapes

```ts
Node   { id, cid, kind: "issue"|"discussion"|"pr"|"commit", source: "jira"|"github"|"slack",
         ref, title, text, author, time /*ISO event_time*/, url, paths?: string[], scope }
         // id == cid == canonical_id. scope: "owner/repo" | Jira project key | Slack channel id.
         // built ONLY by hackfront.api.mapping.to_node
Edge   { from, to, rel: "CONTAINS"|"REFERENCES"|"REPLIES_TO"|"PARENT_OF"|"CHANGES",
         origin: "structural"|"text", locator }       // no INFERRED edges: the graph holds only explicit links
Cite   { node, quote? }          // quote, when present, is VERBATIM text of that node (verified server-side)
Claim  { id, text, status: "supported"|"inferred"|"unknown", note?, cites: Cite[], afterStep: number }
Step   { kind: "understand"|"plan"|"tool"|"gap"|"synthesize", label, detail, ms }
Check  { label, state: "holds"|"changed"|"unknown", detail }
Investigation { id, question, mode: "why"|"debug"|"change", file?, line?, summary, nodes: string[] /*evidence ids*/,
                claims: Claim[], gaps: string[], trace: Step[], checks: Check[],
                excluded: { node, reason }[], confidence: "high"|"medium"|"low",
                provider, model, prompt_version, created_at }
Graph  { nodes: Node[], edges: Edge[] }
```

Claim semantics (enforced in code, not by the model):
- `supported`: at least one cite whose node is in the retrieved evidence and whose `quote` (if given) occurs verbatim
  in that node's text (whitespace-normalised, case-insensitive). Cites failing this are dropped; a claim left with
  no verified cite is downgraded to `inferred` with a note saying a citation could not be verified.
- `inferred`: reasoning beyond what any source states; `note` says why. May have cites.
- `unknown`: something the evidence cannot establish; no cites.
- `excluded`: evidence retrieved but not cited. Reason is deterministic: "Keyword match only: no explicit link to the
  evidence used." when no edge connects it to any cited node, else "Linked, but not needed for this answer."
- `checks` are deterministic graph facts, e.g. "Later commits touching <file>" (holds = none after the newest cited
  commit; changed = lists them) and cited Jira issue status (`unknown` state, detail "Jira status: Done (as of last sync)").
- `afterStep`: index into `trace` after which the claim may be revealed during replay; default `len(trace)-1`.

## Endpoints

| Method + path | Body / query | Response |
|---|---|---|
| `GET /api/workbench` | | `{workspace:{slug,name}, connected:{repos[],jira[],slack[]}, catalog:{repos[],jira[],slack[]}, indexed_repos:string[], neo4j:{ok,counts?}, sources:{github,jira,slack:{token_present}}, providers:[{name,model,configured}]}`. `slug` is `"local"`; `catalog` = connected plus every scope present in the graph. |
| `PUT /api/workspace`, `POST /api/sync`, `POST /api/demo` | existing | existing (`/api/sync` and `/api/demo` return `{summaries, complete}`) |
| `GET /api/graph` | | `Graph` of all non-stub artifacts (cap 3000 nodes) |
| `GET /api/repo/{owner}/{repo}/files` | | `{files: string[]}` paths touched by ingested commits of that repo |
| `GET /api/repo/{owner}/{repo}/file?path=` | | `{path, lines:[{text, blame: nodeId\|null}], complete: boolean, note?: string}`; blame by replaying the ingested commit patches (oldest -> newest); `complete=false` + note when history is missing or a patch does not apply; never guessed |
| `POST /api/investigate` | `{question, mode?, provider?, model?, file?, line?, repo?}` (`repo` = `owner/repo`, optional when exactly one repo is indexed) | SSE: `event: trace` `{step: Step}` per step as it happens; then `event: investigation` `{investigation, graph: Graph}`; or `event: error` `{message}`. The investigation is persisted. |
| `GET /api/investigations` | | `[{id, question, file, line, confidence, created_at}]` newest first |
| `GET /api/investigations/{id}` | | `{investigation, graph: Graph}` |

`file`+`line` anchor an investigation: the server derives the line text and its blame commit (from the same blame
code) and passes them to the agent as seeds (blame commit id is "seen"; `file_history(file)` is seeded).
Validation: question 1-8000 chars; `file` a relative POSIX path without `..`; `line` positive int; mode/provider known.

## Ownership (parallel workstreams; do not edit outside your files)

- MVP-BLAME: `src/hackfront/ingest/blame.py`, `src/hackfront/api/workbench.py`, demo data in `src/hackfront/ingest/demo/`, tests `tests/ingest/unit/test_blame.py`, `tests/api/test_workbench.py`.
- MVP-CLAIMS: `src/hackfront/agent/**` (claims schema, verbatim-quote verification, excluded/checks/gaps, anchor, per-call trace rows, `agent/investigation.py` assembler), `src/hackfront/api/investigate.py`, tests `tests/agent/**`, `tests/api/test_investigate.py`.
- MVP-WEB: `web/**` (swap mock data for the API; keep the owner's design/UX intact).
- Shared and lead-owned: `src/hackfront/api/mapping.py`, `src/hackfront/api/app.py`, `config.py`, `docs/`.
