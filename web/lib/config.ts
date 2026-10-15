"use client";
// What a workspace has connected. Mock: persisted in localStorage, shared across components via an event.
import { useCallback, useEffect, useState } from "react";
import { WORKSPACES, type WsConfig } from "./workspaces";

const KEY = (ws: string) => `wb-config:${ws}`;
const EVT = "wb-config";

export function useConfig(ws: string) {
  const def = WORKSPACES.find((w) => w.slug === ws)?.defaults ?? { repos: [], jira: [], slack: [] };
  const [cfg, set] = useState<WsConfig>(def);
  const load = useCallback(() => {
    try { const raw = localStorage.getItem(KEY(ws)); set(raw ? JSON.parse(raw) : def); } catch { set(def); }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ws]);
  useEffect(() => { load(); window.addEventListener(EVT, load); return () => window.removeEventListener(EVT, load); }, [load]);

  const toggle = (kind: keyof WsConfig, id: string) => {
    const next = { ...cfg, [kind]: cfg[kind].includes(id) ? cfg[kind].filter((x) => x !== id) : [...cfg[kind], id] };
    try { localStorage.setItem(KEY(ws), JSON.stringify(next)); } catch {}
    set(next);
    window.dispatchEvent(new Event(EVT));
  };
  return [cfg, toggle] as const;
}
