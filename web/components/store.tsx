"use client";
import { useRouter } from "next/navigation";
import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { BY_ID, EDGES, FILES, INVESTIGATIONS, investigationFor, type Investigation, type Kind } from "@/lib/data";
import { useConfig } from "@/lib/config";
import { isLocked } from "@/lib/workspaces";

export type Tab = "timeline" | "graph";
export type Verdict = "confirmed" | "disputed";

interface Ctx {
  inv: Investigation | null;
  base: string; // /w/[ws]/[repo]
  locked: (id: string) => boolean;
  file: string;
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
  setTab: (t: Tab) => void;
  toggleKind: (k: Kind) => void;
  setShowInferred: (b: boolean) => void;
  hoverNodes: (ids: string[]) => void;
  setClaim: (id: string | null) => void;
  selectNode: (id: string | null) => void;
  stepNode: (dir: 1 | -1) => void;
  selectLine: (line: number) => void;
  openInvestigation: (id: string) => void;
  replay: () => void;
  vote: (claimId: string, v: Verdict) => void;
}

const C = createContext<Ctx>(null as never);
export const useWb = () => useContext(C);

const FB_KEY = "why-workbench:feedback";

/** Route-driven: the page decides the file (and optionally the investigation); the rest is in-page interaction. */
export function Provider({ ws, repo, file, invId: initialInv, children }: { ws: string; repo: string; file: string; invId: string | null; children: ReactNode }) {
  const router = useRouter();
  const [cfg] = useConfig(ws);
  const base = `/w/${ws}/${repo}`;
  const locked = useCallback((id: string) => isLocked(BY_ID[id], cfg), [cfg]);
  const start = INVESTIGATIONS.find((i) => i.id === initialInv) ?? null;
  const [invId, setInvId] = useState<string | null>(start?.id ?? null);
  const [line, setLine] = useState<number | null>(start?.line ?? null);
  const [selected, setSelected] = useState<string | null>(null);
  const [hover, setHover] = useState<string[]>([]);
  const [claim, setClaim] = useState<string | null>(null);
  const [tab, setTab] = useState<Tab>("timeline");
  const [hiddenKinds, setHidden] = useState<Kind[]>([]);
  const [showInferred, setShowInferred] = useState(true);
  const [step, setStep] = useState(start?.trace.length ?? 0);
  const [feedback, setFeedback] = useState<Record<string, Verdict>>({});
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);

  const inv = INVESTIGATIONS.find((i) => i.id === invId) ?? null;

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
  useEffect(() => () => clearTimeout(timer.current), []);

  const visible = useMemo(() => {
    if (!inv) return [];
    return inv.nodes
      .filter((id) => !hiddenKinds.includes(BY_ID[id].kind) && !locked(id))
      .sort((a, b) => BY_ID[a].time.localeCompare(BY_ID[b].time));
  }, [inv, hiddenKinds, locked]);

  const lit = useMemo(() => {
    const s = new Set(hover);
    inv?.claims.find((x) => x.id === claim)?.cites.forEach((x) => s.add(x.node));
    return s;
  }, [hover, claim, inv]);

  const selectLine = useCallback((l: number) => {
    setLine(l); setSelected(null); setClaim(null);
    const blame = FILES.find((x) => x.path === file)!.lines[l - 1].blame;
    // a blamed commit with no explicit links explains nothing: show the empty state instead of guessing
    const linked = EDGES.some((e) => e.rel !== "INFERRED" && (e.from === blame || e.to === blame));
    const next = linked ? investigationFor(blame) ?? null : null;
    if (next?.id !== invId) { setInvId(next?.id ?? null); if (next) runTrace(next); }
    if (next) setSelected(blame);
  }, [file, invId, runTrace]);

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
    inv, base, locked, file, line, selected, claim, lit, tab, hiddenKinds, showInferred, step, feedback, visible,
    setTab, setShowInferred, setClaim,
    toggleKind: (k) => setHidden((h) => (h.includes(k) ? h.filter((x) => x !== k) : [...h, k])),
    hoverNodes: setHover, selectNode: setSelected, stepNode, selectLine,
    openInvestigation: (id) => router.push(`${base}/why/${id}`),
    replay: () => inv && runTrace(inv), vote,
  };
  return <C.Provider value={value}>{children}</C.Provider>;
}
