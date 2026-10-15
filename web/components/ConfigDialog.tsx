"use client";
import { useEffect } from "react";
import { useConfig } from "@/lib/config";
import { CATALOG, INDEXED_REPO, WORKSPACES, type WsConfig } from "@/lib/workspaces";
import { Icon, type IconName } from "./icons";

const GROUPS: { kind: keyof WsConfig; title: string; icon: IconName; items: string[] }[] = [
  { kind: "repos", title: "Repositories", icon: "repo", items: CATALOG.repos },
  { kind: "jira", title: "Jira projects", icon: "issue", items: CATALOG.jira },
  { kind: "slack", title: "Slack channels", icon: "discussion", items: CATALOG.slack },
];

export function Switch({ on, label }: { on: boolean; label: string }) {
  return (
    <span role="switch" aria-checked={on} aria-label={label}
      className={`relative block h-[18px] w-8 shrink-0 rounded-full transition-colors ${on ? "bg-accent" : "bg-line2"}`}>
      <i className={`absolute top-[2px] h-[14px] w-[14px] rounded-full bg-bg shadow transition-all ${on ? "left-[16px]" : "left-[2px]"}`} />
    </span>
  );
}

export default function ConfigDialog({ ws, onClose }: { ws: string; onClose: () => void }) {
  const [cfg, toggle] = useConfig(ws);
  const name = WORKSPACES.find((w) => w.slug === ws)?.name;
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-[2px]" onMouseDown={onClose}>
      <div role="dialog" aria-label={`Connections for ${name}`} onMouseDown={(e) => e.stopPropagation()}
        className="fade-up flex max-h-[80vh] w-[480px] max-w-[94vw] flex-col overflow-hidden rounded-xl border border-line2 bg-bg shadow-2xl shadow-black/30">
        <div className="flex items-center border-b border-line px-5 py-3.5">
          <h2 className="font-semibold">Connections <span className="font-normal text-dim">· {name}</span></h2>
          <button onClick={onClose} aria-label="Close" className="ml-auto text-dim hover:text-fg"><Icon name="x" size={15} /></button>
        </div>
        <div className="space-y-5 overflow-auto px-5 py-4">
          {GROUPS.map((g) => (
            <section key={g.kind}>
              <h3 className="label mb-1.5 flex items-center gap-1.5"><Icon name={g.icon} size={12} />{g.title}<span className="ml-auto normal-case tracking-normal">{cfg[g.kind].length}</span></h3>
              <ul>
                {g.items.map((id) => {
                  const on = cfg[g.kind].includes(id);
                  return (
                    <li key={id}>
                      <button onClick={() => toggle(g.kind, id)} className="flex h-9 w-full items-center gap-2 rounded-md px-1.5 text-left hover:bg-panel">
                        <span className="font-mono text-[12.5px]">{id}</span>
                        {g.kind === "repos" && on && id !== INDEXED_REPO && <span className="text-[11px] text-warn">indexing…</span>}
                        <span className="ml-auto"><Switch on={on} label={id} /></span>
                      </button>
                    </li>
                  );
                })}
              </ul>
            </section>
          ))}
        </div>
        <div className="flex justify-end border-t border-line px-5 py-3">
          <button onClick={onClose} className="h-8 rounded-md bg-fg px-4 text-[12.5px] font-medium text-bg hover:opacity-90">Done</button>
        </div>
      </div>
    </div>
  );
}
