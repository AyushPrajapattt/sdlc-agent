"use client";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { investigate } from "@/lib/api";
import { useData, useFile } from "@/lib/data";
import type { CodeFile, Investigation, Kind, Step } from "@/lib/types";

export type Tab = "timeline" | "graph";
export type Verdict = "confirmed" | "disputed";

interface Ctx {
  inv: Investigation | null;
  base: string; // /w/[ws]/[repo]
  repoName: string; // owner/repo
  locked: (id: string) => boolean;
  file: string | null;
  code: { data: CodeFile | null; loading: boolean; error: string };
  line: number | null;
  selected: string | null;
  claim: string | null;
  lit: Set<string>;
  tab: Tab;
  hiddenKinds: Kind[];
  showInferred: boolean;
  step: number;
  feedback: Record<string, Verdict>;
  visible: string[]; // node ids shown in evidence, chronological
  running: boolean; // an /api/investigate stream is open
  live: Step[]; // trace steps received so far
  askError: string;
  provider: string; // "" = server default
  setProvider: (p: string) => void;
  setTab: (t: Tab) => void;
  toggleKind: (k: Kind) => void;
  setShowInferred: (b: boolean) => void;
  hoverNodes: (ids: string[]) => void;
  setClaim: (id: string | null) => void;
  selectNode: (id: string | null) => void;
  stepNode: (dir: 1 | -1) => void;
  selectLine: (line: number) => void;
  ask: (question: string) => void;
  openInvestigation: (id: string) => void;
  replay: () => void;
  vote: (claimId: string, v: Verdict) => void;
}

const C = createContext<Ctx>(null as never);
export const useWb = () => useContext(C);

const FB_KEY = "why-workbench:feedback";
const LINE_QUESTION = "Why is this line the way it is?";

/** Route-driven: the page decides the file and (for stored investigations) the investigation; the rest is in-page interaction. */
export function Provider({ ws, repo, repoName, file, inv: initial, children }: { ws: string; repo: string; repoName: string; file: string | null; inv: Investigation | null; children: ReactNode }) {
  const router = useRouter();
  const { byId, investigations, explained, isLocked, absorb, remember } = useData();
  const base = `/w/${ws}/${repo}`;
  const code = useFile(repoName, file);
  const locked = useCallback((id: string) => (byId[id] ? isLocked(byId[id]) : false), [byId, isLocked]);
  const [inv, setInv] = useState<Investigation | null>(initial);
  const [line, setLine] = useState<number | null>(initial?.line ?? null);
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string[]>([]);
  const [claim, setClaim] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("timeline");
  const [hiddenKinds, setHidden] = useState<Kind[]>([]);
  const [showInferred, setShowInferred] = useState(true);
  const [step, setStep] = useState(initial?.trace.length ?? 0);
  const [feedback, setFeedback] = useState<Record<string, Verdict>>({});
  const [running, setRunning] = useState(false);
  const [live, setLive] = useState<Step[]>([]);
  const [askError, setAskError] = useState("");
  const [provider, setProvider] = useState("");
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  const ctl = useRef<AbortController>(undefined);

  useEffect(() => {
    try { setFeedback(JSON.parse(localStorage.getItem(FB_KEY) ?? "{}")); } catch {}
  }, []);

  const runTrace = useCallback((target: Investigation) => {
    clearTimeout(timer.current);
    setStep(0);
    const tick = (i: number) => {
      if (i >= target.trace.length) return;
      timer.current = setTimeout(() => { setStep(i + 1); tick(i + 1); }, Math.min(target.trace[i].ms, 650));
    };
    tick(0);
  }, []);
  useEffect(() => () => { clearTimeout(timer.current); ctl.current?.abort(); }, []);

  const visible = useMemo(() => {
    if (!inv) return [];
    return inv.nodes
      .filter((id) => byId[id] && !hiddenKinds.includes(byId[id].kind) && !locked(id))
      .sort((a, b) => byId[a].time.localeCompare(byId[b].time));
  }, [inv, byId, hiddenKinds, locked]);

  const lit = useMemo(() => {
    const s = new Set(hover);
    inv?.claims.find((x) => x.id === claim)?.cites.forEach((x) => s.add(x.node));
    return s;
  }, [hover, claim, inv]);

  const openInvestigation = useCallback((id: string) => router.push(`${base}/why/${id}`), [router, base]);

  /** Stream a new investigation, then open it. Errors stay inline as the server's safe message. */
  const ask = useCallback((question: string, anchor?: { file: string; line: number }) => {
    ctl.current?.abort();
    const c = new AbortController();
    ctl.current = c;
    setRunning(true); setLive([]); setAskError(""); setSelected(null); setClaim(null);
    investigate({ question, mode: "why", provider: provider || undefined, repo: repoName, ...anchor }, (s) => setLive((l) => [...l, s]), c.signal)
      .then((r) => {
        absorb(r.graph); remember(r.investigation);
        setRunning(false);
        openInvestigation(r.investigation.id);
      })
      .catch((e: Error) => {
        if (c.signal.aborted) return;
        setRunning(false);
        setAskError(e.message);
      });
  }, [provider, repoName, absorb, remember, openInvestigation]);

  const selectLine = useCallback((l: number) => {
    setLine(l); setSelected(null); setClaim(null); setAskError("");
    const blame = code.data?.lines[l - 1]?.blame;
    // a blamed commit with no explicit links explains nothing: show the empty state instead of guessing
    if (!blame || !file || !explained(blame)) { setInv(null); return; }
    if (inv && inv.file === file && inv.line === l) { setSelected(blame); return; }
    const stored = investigations.find((r) => r.file === file && r.line === l);
    if (stored) { openInvestigation(stored.id); return; }
    setInv(null);
    ask(LINE_QUESTION, { file, line: l });
  }, [code.data, file, inv, investigations, explained, openInvestigation, ask]);

  const stepNode = useCallback((dir: 1 | -1) => {
    if (!visible.length) return;
    const i = selected ? visible.indexOf(selected) : -1;
    setSelected(visible[Math.min(visible.length - 1, Math.max(0, i + dir))]);
  }, [visible, selected]);

  const vote = useCallback((id: string, v: Verdict) => {
    setFeedback((f) => {
      const next = { ...f };
      if (next[id] === v) delete next[id]; else next[id] = v;
      try { localStorage.setItem(FB_KEY, JSON.stringify(next)); } catch {}
      return next;
    });
  }, []);

  const value: Ctx = {
    inv, base, repoName, locked, file, code, line, selected, claim, lit, tab, hiddenKinds, showInferred, step, feedback, visible,
    running, live, askError, provider, setProvider,
    setTab, setShowInferred, setClaim,
    toggleKind: (k) => setHidden((h) => (h.includes(k) ? h.filter((x) => x !== k) : [...h, k])),
    hoverNodes: setHover, selectNode: setSelected, stepNode, selectLine,
    ask: (q) => ask(q), openInvestigation,
    replay: () => inv && runTrace(inv), vote,
  };
  return <C.Provider value={value}>{children}</C.Provider>;
}
