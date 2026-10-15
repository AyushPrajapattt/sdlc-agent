// Shapes of docs/workbench-api.md (the backend contract) plus pure helpers. No data lives here.

export type Kind = "issue" | "discussion" | "pr" | "commit";
export type Status = "supported" | "inferred" | "unknown";

export interface Node {
  id: string;
  cid: string; // canonical id as stored in Neo4j (== id)
  kind: Kind;
  source: "jira" | "github" | "slack";
  ref: string; // short human label
  title: string;
  text: string;
  author: string;
  time: string;
  url: string;
  paths?: string[];
  scope: string; // "owner/repo" | Jira project key | Slack channel id
}

export interface Edge {
  from: string;
  to: string;
  // INFERRED is kept for forward compatibility; the backend graph holds only explicit links today.
  rel: "CONTAINS" | "REFERENCES" | "REPLIES_TO" | "PARENT_OF" | "CHANGES" | "INFERRED";
  origin: "structural" | "text";
  locator: string;
  why?: string; // only for inferred edges
}

export interface Graph { nodes: Node[]; edges: Edge[] }

export interface Cite {
  node: string;
  quote?: string;
}
export interface Claim {
  id: string;
  text: string;
  status: Status;
  note?: string;
  cites: Cite[];
  afterStep: number; // revealed once the trace reaches this step
}
export interface Step {
  kind: "understand" | "plan" | "tool" | "gap" | "synthesize";
  label: string;
  detail: string;
  ms: number;
}
export interface Check {
  label: string;
  state: "holds" | "changed" | "unknown";
  detail: string;
}
export interface Investigation {
  id: string;
  question: string;
  mode: "why" | "debug" | "change";
  file?: string;
  line?: number;
  summary: string;
  nodes: string[];
  claims: Claim[];
  gaps: string[];
  trace: Step[];
  checks: Check[];
  excluded: { node: string; reason: string }[];
  confidence: "high" | "medium" | "low";
  provider: string;
  model: string;
  prompt_version: string;
  created_at: string;
}
export interface InvestigationRow {
  id: string;
  question: string;
  file?: string | null;
  line?: number | null;
  confidence: string;
  created_at: string;
}
export interface CodeLine {
  text: string;
  blame: string | null; // node id of the commit, null when unknown
}
export interface CodeFile {
  path: string;
  lines: CodeLine[];
  complete: boolean;
  note?: string;
}

export interface Connected { repos: string[]; jira: string[]; slack: string[] }
export interface Provider { name: string; model: string; configured: boolean }

/** Write-only secret state: values of secret keys are never returned, only a masked hint. */
export interface SecretState { set: boolean; source: "workspace" | "env" | null; value?: string; hint?: string }
export type Secrets = Record<string, SecretState>;
export type IntegrationId = "github" | "jira" | "slack" | "llm";
export interface IntegrationStatus { configured: boolean; secrets: Secrets; targets?: number }

/** Connected targets of a workspace (PUT /api/w/{ws}/workspace). github.repos are bare names under one owner. */
export interface Targets {
  name?: string;
  github: { owner: string; repos: string[] };
  jira: { site: string; projects: string[] };
  slack: { workspace: string; channels: string[] };
}

/** PUT /workspace merges per section: send only what changes. */
export interface TargetsPatch {
  name?: string;
  github?: Partial<Targets["github"]>;
  jira?: Partial<Targets["jira"]>;
  slack?: Partial<Targets["slack"]>;
}

export interface WorkbenchInfo {
  // `targets` is optional: when the server includes the clean workspace here the UI prefills Jira site / Slack subdomain.
  workspace: { slug: string; name: string; demo: boolean; targets?: Targets };
  connected: Connected;
  catalog: Connected;
  indexed_repos: string[];
  neo4j: { ok: boolean; counts?: Record<string, number> };
  integrations: Record<IntegrationId, IntegrationStatus>;
  providers: Provider[];
  names?: { channels: Record<string, string>; users: Record<string, string> };
}

export interface WorkspaceRow {
  slug: string;
  name: string;
  demo: boolean;
  connected: { repos: number; jira: number; slack: number };
  last_sync?: { state: string; finished_at?: string | null } | null;
}

export type StreamStatus = "running" | "done" | "incomplete" | "failed";
export interface SyncStream {
  stream: string;
  status: StreamStatus;
  pages: number;
  fetched: number;
  persisted: number;
  errors: { stage: string; type: string; message: string }[];
}
export type SyncMode = "standard" | "deep";
export interface SyncStatus {
  state: "idle" | "running" | "done" | "failed";
  mode: SyncMode;
  started_at?: string | null;
  finished_at?: string | null;
  streams: SyncStream[];
  totals: { fetched: number; persisted: number; errors: number };
  graph?: { artifacts: number; edges: number; stubs: number } | null;
  complete: boolean;
  error?: string | null;
}

export interface Resource { id: string; name: string; private?: boolean; detail?: string }
export interface TestResult { ok: boolean; detail: string; account?: string }

export const KINDS: { kind: Kind; label: string; color: string }[] = [
  { kind: "issue", label: "Issue", color: "#fb923c" },
  { kind: "discussion", label: "Discussion", color: "#f472b6" },
  { kind: "pr", label: "Pull request", color: "#a78bfa" },
  { kind: "commit", label: "Commit", color: "#60a5fa" },
];
export const KIND_COLOR = Object.fromEntries(KINDS.map((k) => [k.kind, k.color])) as Record<Kind, string>;

export const fmtDate = (iso: string) =>
  new Date(iso).toLocaleDateString("en-GB", { day: "2-digit", month: "short", year: "numeric", timeZone: "UTC" });
export const fmtTime = (iso: string) =>
  new Date(iso).toLocaleTimeString("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
