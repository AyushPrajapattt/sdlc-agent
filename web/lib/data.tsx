"use client";
// Live data: loads /api/workbench, /api/graph and /api/investigations once and exposes the lookups the components use.
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { api } from "./api";
import type { CodeFile, Connected, Edge, Graph, Investigation, InvestigationRow, Node, WorkbenchInfo } from "./types";

export const WS = "local"; // the single local workspace (slug from /api/workbench)
export const repoSlug = (r: string) => r.split("/").pop() ?? r;

interface Data {
  status: "loading" | "ready" | "error";
  error: string;
  warn: string; // graph/investigations failed to load but the workbench did
  info: WorkbenchInfo | null;
  byId: Record<string, Node>;
  edges: Edge[];
  investigations: InvestigationRow[];
  repos: string[]; // owner/repo: connected plus indexed
  connected: Connected;
  hasInferred: boolean;
  version: number; // bumps on refresh so per-file fetches reload
  refresh: () => Promise<void>;
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

export function DataProvider({ children }: { children: ReactNode }) {
  const [info, setInfo] = useState<WorkbenchInfo | null>(null);
  const [status, setStatus] = useState<Data["status"]>("loading");
  const [error, setError] = useState("");
  const [warn, setWarn] = useState("");
  const [byId, setById] = useState<Record<string, Node>>({});
  const [edges, setEdges] = useState<Edge[]>([]);
  const [investigations, setRows] = useState<InvestigationRow[]>([]);
  const [version, setVersion] = useState(0);
  const cache = useRef<Record<string, Investigation>>({});

  const refresh = useCallback(async () => {
    try {
      const wb = await api<WorkbenchInfo>("/api/workbench");
      const [g, rows] = await Promise.allSettled([api<Graph>("/api/graph"), api<InvestigationRow[]>("/api/investigations")]);
      setInfo(wb);
      setById(g.status === "fulfilled" ? Object.fromEntries(g.value.nodes.map((n) => [n.id, n])) : {});
      setEdges(g.status === "fulfilled" ? g.value.edges : []);
      setRows(rows.status === "fulfilled" ? rows.value : []);
      const bad = [g, rows].find((r) => r.status === "rejected");
      setWarn(bad && bad.status === "rejected" ? msg(bad.reason) : "");
      setError("");
      setStatus("ready");
      setVersion((v) => v + 1);
    } catch (e) {
      setError(msg(e));
      setStatus("error");
    }
  }, []);
  useEffect(() => { refresh(); }, [refresh]);

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

  const value = useMemo<Data>(() => {
    const indexed = info?.indexed_repos ?? [];
    // connected repos should be owner/repo; tolerate a bare name by matching an indexed repo
    const full = (r: string) => (r.includes("/") ? r : indexed.find((x) => x.endsWith(`/${r}`)) ?? r);
    const connected = info ? { ...info.connected, repos: info.connected.repos.map(full) } : EMPTY;
    const repos = [...new Set([...connected.repos, ...indexed])];
    const touching = new Map<string, boolean>();
    const parent = new Map<string, string>();
    for (const e of edges) {
      if (e.rel !== "INFERRED") { touching.set(e.from, true); touching.set(e.to, true); }
      if (e.rel === "CONTAINS" && !parent.has(e.to)) parent.set(e.to, e.from);
    }
    return {
      status, error, warn, info, byId, edges, investigations, repos, connected, version,
      hasInferred: edges.some((e) => e.rel === "INFERRED"),
      refresh, absorb, remember, recall: (id) => cache.current[id],
      repoByslug: (slug) => repos.find((r) => repoSlug(r) === slug), // ponytail: two owners with the same repo name collide
      isIndexed: (r) => indexed.includes(r),
      explained: (id) => touching.has(id),
      prOf: (id) => parent.get(id),
      isLocked: (n) => !(n.source === "jira" ? connected.jira : n.source === "slack" ? connected.slack : connected.repos).includes(n.scope),
    };
  }, [status, error, warn, info, byId, edges, investigations, version, refresh, absorb, remember]);

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

const repoApi = (repo: string) => `/api/repo/${repo.split("/").map(encodeURIComponent).join("/")}`;
export const useRepoFiles = (repo: string | undefined) => useRemote<{ files: string[] }>(repo ? `${repoApi(repo)}/files` : null);
export const useFile = (repo: string | undefined, path: string | null) =>
  useRemote<CodeFile>(repo && path ? `${repoApi(repo)}/file?path=${encodeURIComponent(path)}` : null);
