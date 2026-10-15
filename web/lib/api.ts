// Typed fetch helpers for docs/workbench-api.md. Same-origin: next.config.ts proxies /api/* to FastAPI.
import type {
  Graph, IntegrationId, Investigation, InvestigationRow, Resource, SecretState, Step, SyncMode, SyncStatus, Targets, TargetsPatch,
  TestResult, WorkbenchInfo, WorkspaceRow,
} from "./types";

export class ApiError extends Error {
  constructor(message: string, public status: number) { super(message); }
}

const DOWN = "Cannot reach the backend. Is `hackfront serve` running?";

/** Turn a FastAPI error body ({detail: string | [{msg}]}) into one safe line; never raw JSON. */
async function failure(res: Response): Promise<ApiError> {
  let msg = `Request failed (${res.status})`;
  try {
    const d = (await res.json())?.detail;
    if (typeof d === "string") msg = d;
    else if (Array.isArray(d) && d.length) msg = d.map((x) => (typeof x?.msg === "string" ? x.msg : "invalid input")).join("; ");
  } catch {}
  return new ApiError(msg, res.status);
}

export async function api<T>(path: string, init?: { method?: string; body?: unknown; signal?: AbortSignal }): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      method: init?.method ?? "GET",
      headers: init?.body === undefined ? undefined : { "Content-Type": "application/json" },
      body: init?.body === undefined ? undefined : JSON.stringify(init.body),
      signal: init?.signal,
      cache: "no-store",
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(DOWN, 0);
  }
  if (!res.ok) throw await failure(res);
  return res.json() as Promise<T>;
}

export interface InvestigateBody { question: string; mode?: string; provider?: string; model?: string; file?: string; line?: number; repo?: string /* owner/repo, resolves the file */ }
export interface InvestigateResult { investigation: Investigation; graph: Graph }

const W = (ws: string) => `/api/w/${encodeURIComponent(ws)}`;
const slash = (repo: string) => repo.split("/").map(encodeURIComponent).join("/");

/** Typed helpers for every endpoint of docs/workbench-api.md (v2). Workspace-scoped ones take `ws` first. */
export const wsApi = {
  list: () => api<WorkspaceRow[]>("/api/workspaces"),
  create: (name: string, demo = false) => api<{ slug: string; name: string; demo: boolean }>("/api/workspaces", { method: "POST", body: { name, demo } }),
  remove: (ws: string) => api<{ ok: true }>(`/api/workspaces/${encodeURIComponent(ws)}`, { method: "DELETE" }),
  workbench: (ws: string) => api<WorkbenchInfo>(`${W(ws)}/workbench`),
  saveTargets: (ws: string, body: TargetsPatch) => api<Targets>(`${W(ws)}/workspace`, { method: "PUT", body }),
  saveSecrets: (ws: string, body: Record<string, string>) => api<Record<string, SecretState>>(`${W(ws)}/secrets`, { method: "PUT", body }),
  test: (ws: string, id: IntegrationId) => api<TestResult>(`${W(ws)}/integrations/${id}/test`, { method: "POST" }),
  resources: (ws: string, id: Exclude<IntegrationId, "llm">) => api<{ resources: Resource[] }>(`${W(ws)}/integrations/${id}/resources`),
  syncStart: (ws: string, mode: SyncMode) => api<SyncStatus>(`${W(ws)}/sync`, { method: "POST", body: { mode } }),
  syncStatus: (ws: string, signal?: AbortSignal) => api<SyncStatus>(`${W(ws)}/sync`, { signal }),
  graph: (ws: string) => api<Graph>(`${W(ws)}/graph`),
  investigations: (ws: string) => api<InvestigationRow[]>(`${W(ws)}/investigations`),
  investigation: (ws: string, id: string) => api<{ investigation: Investigation; graph: Graph }>(`${W(ws)}/investigations/${encodeURIComponent(id)}`),
  files: (ws: string, repo: string, signal?: AbortSignal) => api<{ files: string[] }>(`${W(ws)}/repo/${slash(repo)}/files`, { signal }),
  fileUrl: (ws: string, repo: string, path: string) => `${W(ws)}/repo/${slash(repo)}/file?path=${encodeURIComponent(path)}`,
};

/** POST /api/w/{ws}/investigate and read its SSE stream: onStep per `trace` event, resolves on `investigation`, throws on `error`. */
export async function investigate(ws: string, body: InvestigateBody, onStep: (s: Step) => void, signal?: AbortSignal): Promise<InvestigateResult> {
  let res: Response;
  try {
    res = await fetch(`${W(ws)}/investigate`, {
      method: "POST", headers: { "Content-Type": "application/json", Accept: "text/event-stream" },
      body: JSON.stringify(body), signal, cache: "no-store",
    });
  } catch (e) {
    if ((e as Error).name === "AbortError") throw e;
    throw new ApiError(DOWN, 0);
  }
  if (!res.ok) throw await failure(res);
  if (!res.body) throw new ApiError("The server sent no stream", res.status);

  const reader = res.body.pipeThrough(new TextDecoderStream()).getReader();
  const out: { result?: InvestigateResult } = {};
  const frame = (raw: string) => {
    let event = "message", data = "";
    for (const line of raw.split("\n")) {
      if (line.startsWith("event:")) event = line.slice(6).trim();
      else if (line.startsWith("data:")) data += (data ? "\n" : "") + line.slice(5).replace(/^ /, "");
    }
    if (!data) return;
    let p: { step?: Step; message?: string } & Partial<InvestigateResult>;
    try { p = JSON.parse(data); } catch { return; }
    if (event === "trace" && p.step) onStep(p.step);
    else if (event === "investigation" && p.investigation && p.graph) out.result = { investigation: p.investigation, graph: p.graph };
    else if (event === "error") throw new ApiError(typeof p.message === "string" && p.message ? p.message : "The investigation failed", 500);
  };
  let buf = "";
  for (;;) {
    const { done, value } = await reader.read();
    if (value) {
      buf += value.replace(/\r\n/g, "\n");
      let i: number;
      while ((i = buf.indexOf("\n\n")) >= 0) { frame(buf.slice(0, i)); buf = buf.slice(i + 2); }
    }
    if (done) break;
  }
  if (buf.trim()) frame(buf);
  if (!out.result) throw new ApiError("The investigation ended without a result", 500);
  return out.result;
}
