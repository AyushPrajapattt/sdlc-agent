"use client";
// Live data of the workspace in the URL (/w/[ws]/...): workbench info, graph, investigations and the sync job, plus the workspace list.
// The provider is keyed by ws, so switching workspace discards everything and reloads.
import { usePathname } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { ApiError, api, wsApi } from "./api";
import type {
  CodeFile, Connected, Edge, Graph, Investigation, InvestigationRow, Node, SyncMode, SyncStatus, Targets, TargetsPatch, WorkbenchInfo, WorkspaceRow,
} from "./types";

export const repoSlug = (r: string) => r.split("/").pop() ?? r;

interface Data {
  ws: string | undefined; // from the route; undefined outside /w/[ws]
  status: "idle" | "loading" | "ready" | "error" | "notfound";
  error: string;
  warn: string; // graph/investigations failed to load but the workbench did
  info: WorkbenchInfo | null;
  workspaces: WorkspaceRow[] | null;
  workspacesError: string;
  byId: Record<string, Node>;
  edges: Edge[];
  investigations: InvestigationRow[];
  repos: string[]; // owner/repo: connected plus indexed
  connected: Connected;
  targets: Targets | null; // current targets in the shape PUT /workspace takes
  hasInferred: boolean;
  version: number; // bumps on refresh so per-file fetches reload
  sync: SyncStatus | null;
  syncLoaded: boolean;
  refresh: () => Promise<void>;
  refreshWorkspaces: () => Promise<void>;
  saveTargets: (patch: TargetsPatch) => Promise<void>;
  startSync: (mode: SyncMode) => Promise<void>;
  absorb: (g: Graph) => void; // merge nodes/edges returned with an investigation
  remember: (inv: Investigation) => void;
  recall: (id: string) => Investigation | undefined;
  repoByslug: (slug: string) => string | undefined;
  isIndexed: (repo: string) => boolean;
  explained: (nodeId: string) => boolean; // has at least one non-INFERRED edge
  prOf: (commitId: string) => string | undefined;
  isLocked: (n: Node) => boolean;
}

const Ctx = createContext<Data>(null as never);
export const useData = () => useContext(Ctx);

const EMPTY: Connected = { repos: [], jira: [], slack: [] };
const msg = (e: unknown) => (e instanceof Error ? e.message : "Request failed");

/** `/w/<ws>/...` -> ws */
function wsFromPath(path: string): string | undefined {
  const [, w, ws] = path.split("/");
  if (w !== "w" || !ws) return undefined;
  try { return decodeURIComponent(ws); } catch { return ws; }
}

export function DataProvider({ children }: { children: ReactNode }) {
  const ws = wsFromPath(usePathname());
  return <Inner key={ws ?? ""} ws={ws}>{children}</Inner>;
}

function Inner({ ws, children }: { ws: string | undefined; children: ReactNode }) {
  const [info, setInfo] = useState<WorkbenchInfo | null>(null);
  const [status, setStatus] = useState<Data["status"]>(ws ? "loading" : "idle");
  const [error, setError] = useState("");
  const [warn, setWarn] = useState("");
  const [workspaces, setWorkspaces] = useState<WorkspaceRow[] | null>(null);
  const [workspacesError, setWorkspacesError] = useState("");
  const [byId, setById] = useState<Record<string, Node>>({});
  const [edges, setEdges] = useState<Edge[]>([]);
  const [investigations, setRows] = useState<InvestigationRow[]>([]);
  const [version, setVersion] = useState(0);
  const [saved, setSaved] = useState<Targets | null>(null); // last PUT /workspace response: knows the Jira site / Slack subdomain
  const [sync, setSync] = useState<SyncStatus | null>(null);
  const [syncLoaded, setSyncLoaded] = useState(false);
  const cache = useRef<Record<string, Investigation>>({});

  const refreshWorkspaces = useCallback(async () => {
    try { setWorkspaces(await wsApi.list()); setWorkspacesError(""); } catch (e) { setWorkspacesError(msg(e)); }
  }, []);

  const refresh = useCallback(async () => {
    if (!ws) return;
    try {
      const wb = await wsApi.workbench(ws);
      const [g, rows] = await Promise.allSettled([wsApi.graph(ws), wsApi.investigations(ws)]);
      setInfo(wb);
      setById(g.status === "fulfilled" ? Object.fromEntries(g.value.nodes.map((n) => [n.id, n])) : {});
      setEdges(g.status === "fulfilled" ? g.value.edges : []);
      setRows(rows.status === "fulfilled" ? rows.value : []);
      const bad = [g, rows].find((r) => r.status === "rejected");
      setWarn(bad && bad.status === "rejected" ? msg(bad.reason) : "");
      setError("");
      setStatus("ready");
      setVersion((v) => v + 1);
      refreshWorkspaces();
    } catch (e) {
      setError(msg(e));
      setStatus(e instanceof ApiError && e.status === 404 ? "notfound" : "error");
    }
  }, [ws, refreshWorkspaces]);
  useEffect(() => { refresh(); }, [refresh]);
  useEffect(() => { refreshWorkspaces(); }, [refreshWorkspaces]);

  // Sync job: status lives on the server, so load it once and poll every second while it runs (survives a page reload).
  useEffect(() => {
    if (!ws) return;
    const ctl = new AbortController();
    wsApi.syncStatus(ws, ctl.signal).then(setSync, () => {}).finally(() => { if (!ctl.signal.aborted) setSyncLoaded(true); });
    return () => ctl.abort();
  }, [ws]);
  const running = sync?.state === "running";
  useEffect(() => {
    if (!ws || !running) return;
    const ctl = new AbortController();
    const t = setInterval(() => {
      wsApi.syncStatus(ws, ctl.signal).then((s) => {
        if (ctl.signal.aborted) return;
        setSync(s);
        if (s.state !== "running") refresh(); // new artifacts: reload graph and indexed repos
      }, () => {}); // a missed poll is retried on the next tick
    }, 1000);
    return () => { clearInterval(t); ctl.abort(); };
  }, [ws, running, refresh]);

  const startSync = useCallback(async (mode: SyncMode) => {
    if (!ws) return;
    try {
      setSync(await wsApi.syncStart(ws, mode));
    } catch (e) {
      if (e instanceof ApiError && e.status === 409) wsApi.syncStatus(ws).then(setSync, () => {}); // already running: follow it
      throw e;
    }
  }, [ws]);

  const absorb = useCallback((g: Graph) => {
    setById((m) => ({ ...m, ...Object.fromEntries(g.nodes.map((n) => [n.id, n])) }));
    setEdges((es) => {
      const key = (e: Edge) => `${e.from}|${e.rel}|${e.to}`;
      const seen = new Set(es.map(key));
      return [...es, ...g.edges.filter((e) => !seen.has(key(e)))];
    });
  }, []);

  const remember = useCallback((inv: Investigation) => {
    cache.current[inv.id] = inv;
    setRows((rs) => (rs.some((r) => r.id === inv.id) ? rs
      : [{ id: inv.id, question: inv.question, file: inv.file, line: inv.line, confidence: inv.confidence, created_at: inv.created_at }, ...rs]));
  }, []);

  const derived = useMemo(() => {
    const indexed = info?.indexed_repos ?? [];
    // connected repos should be owner/repo; tolerate a bare name by matching an indexed repo
    const full = (r: string) => (r.includes("/") ? r : indexed.find((x) => x.endsWith(`/${r}`)) ?? r);
    const connected = info ? { ...info.connected, repos: info.connected.repos.map(full) } : EMPTY;
    const repos = [...new Set([...connected.repos, ...indexed])];
    const t = saved ?? info?.workspace.targets;
    const owner = t?.github.owner || connected.repos.find((r) => r.includes("/"))?.split("/")[0] || "";
    const bare = (r: string) => (r.startsWith(`${owner}/`) ? r.slice(owner.length + 1) : r);
    const targets: Targets | null = info ? {
      github: { owner, repos: connected.repos.map(bare) },
      jira: { site: t?.jira.site ?? "", projects: connected.jira },
      slack: { workspace: t?.slack.workspace ?? "", channels: connected.slack },
    } : null;
    return { indexed, connected, repos, targets };
  }, [info, saved]);

  // The server merges per section, so a patch only needs the fields it changes.
  const saveTargets = useCallback(async (patch: TargetsPatch) => {
    if (!ws) return;
    setSaved(await wsApi.saveTargets(ws, patch));
    await refresh();
  }, [ws, refresh]);

  const value = useMemo<Data>(() => {
    const { indexed, connected, repos, targets } = derived;
    const touching = new Map<string, boolean>();
    const parent = new Map<string, string>();
    for (const e of edges) {
      if (e.rel !== "INFERRED") { touching.set(e.from, true); touching.set(e.to, true); }
      if (e.rel === "CONTAINS" && !parent.has(e.to)) parent.set(e.to, e.from);
    }
    return {
      ws, status, error, warn, info, workspaces, workspacesError, byId, edges, investigations, repos, connected, targets, version,
      sync, syncLoaded,
      hasInferred: edges.some((e) => e.rel === "INFERRED"),
      refresh, refreshWorkspaces, saveTargets, startSync, absorb, remember, recall: (id) => cache.current[id],
      repoByslug: (slug) => repos.find((r) => repoSlug(r) === slug), // ponytail: two owners with the same repo name collide
      isIndexed: (r) => indexed.includes(r),
      explained: (id) => touching.has(id),
      prOf: (id) => parent.get(id),
      isLocked: (n) => !(n.source === "jira" ? connected.jira : n.source === "slack" ? connected.slack : connected.repos).includes(n.scope),
    };
  }, [ws, status, error, warn, info, workspaces, workspacesError, byId, edges, investigations, derived, version, sync, syncLoaded, refresh, refreshWorkspaces, saveTargets, startSync, absorb, remember]);

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export const lockedReason = (n: Node) => `${n.source === "jira" ? "Jira" : n.source === "slack" ? "Slack" : "Repository"} ${n.scope}`;

/** GET a url once per (url, refresh); null skips. */
export function useRemote<T>(url: string | null) {
  const { version } = useData();
  const [st, set] = useState<{ key: string; data: T | null; error: string }>({ key: "", data: null, error: "" });
  const key = url ? `${url}#${version}` : "";
  useEffect(() => {
    if (!url) return;
    const ctl = new AbortController();
    api<T>(url, { signal: ctl.signal }).then(
      (data) => set({ key, data, error: "" }),
      (e) => { if (e?.name !== "AbortError") set({ key, data: null, error: msg(e) }); },
    );
    return () => ctl.abort();
  }, [url, key]);
  const fresh = st.key === key;
  return { data: fresh ? st.data : null, error: fresh ? st.error : "", loading: !!url && !fresh };
}

export function useRepoFiles(repo: string | undefined) {
  const { ws } = useData();
  return useRemote<{ files: string[] }>(ws && repo ? `/api/w/${encodeURIComponent(ws)}/repo/${repo.split("/").map(encodeURIComponent).join("/")}/files` : null);
}
export function useFile(repo: string | undefined, path: string | null) {
  const { ws } = useData();
  return useRemote<CodeFile>(ws && repo && path ? wsApi.fileUrl(ws, repo, path) : null);
}
