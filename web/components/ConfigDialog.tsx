"use client";
import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useData } from "@/lib/data";
import { Icon, type IconName } from "./icons";

interface WorkspaceFile {
  github: { owner: string; repos: string[] }; // repos are bare names; owner is shared
  jira: { site: string; projects: string[] };
  slack: { workspace: string; channels: string[] };
}
interface SyncResult { summaries: { stream: string; counts?: { persisted?: number }; complete: boolean; errors?: unknown[] }[]; complete: boolean }
type Group = "github" | "jira" | "slack";

const GROUPS: { id: Group; title: string; icon: IconName; add: string; field?: { key: "site" | "workspace"; label: string; hint: string } }[] = [
  { id: "github", title: "Repositories", icon: "repo", add: "owner/repo" },
  { id: "jira", title: "Jira projects", icon: "issue", add: "Project key", field: { key: "site", label: "Site", hint: "https://acme.atlassian.net" } },
  { id: "slack", title: "Slack channels", icon: "discussion", add: "Channel id", field: { key: "workspace", label: "Workspace", hint: "workspace subdomain or id" } },
];

export function Switch({ on, label }: { on: boolean; label: string }) {
  return (
    <span role="switch" aria-checked={on} aria-label={label}
      className={`relative block h-[18px] w-8 shrink-0 rounded-full transition-colors ${on ? "bg-accent" : "bg-line2"}`}>
      <i className={`absolute top-[2px] h-[14px] w-[14px] rounded-full bg-bg shadow transition-all ${on ? "left-[16px]" : "left-[2px]"}`} />
    </span>
  );
}

const field = "h-8 min-w-0 flex-1 rounded-md border border-line bg-bg px-2 font-mono text-[12px] outline-none placeholder:text-dim focus:border-line2";
const errText = (e: unknown) => (e instanceof Error ? e.message : "Request failed");
const list = (w: WorkspaceFile, g: Group) => (g === "github" ? w.github.repos : g === "jira" ? w.jira.projects : w.slack.channels);

function withList(w: WorkspaceFile, g: Group, items: string[]): WorkspaceFile {
  return g === "github" ? { ...w, github: { ...w.github, repos: items } }
    : g === "jira" ? { ...w, jira: { ...w.jira, projects: items } }
    : { ...w, slack: { ...w.slack, channels: items } };
}

export default function ConfigDialog({ onClose }: { ws: string; onClose: () => void }) {
  const { info, refresh } = useData();
  const [saved, setSaved] = useState<WorkspaceFile | null>(null);
  const [draft, setDraft] = useState<WorkspaceFile | null>(null);
  const [loadError, setLoadError] = useState("");
  const [adding, setAdding] = useState<Record<Group, string>>({ github: "", jira: "", slack: "" });
  const [error, setError] = useState("");
  const [busy, setBusy] = useState<"" | "save" | "sync" | "demo">("");
  const [result, setResult] = useState<SyncResult | null>(null);

  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  useEffect(() => {
    api<WorkspaceFile>("/api/workspace").then((w) => { setSaved(w); setDraft(w); }, (e) => setLoadError(errText(e)));
  }, []);

  if (!info) return null;
  const dirty = !!draft && JSON.stringify(draft) !== JSON.stringify(saved);
  const owner = draft?.github.owner ?? "";
  const full = (name: string) => (name.includes("/") || !owner ? name : `${owner}/${name}`);
  const labelOf = (g: Group, id: string) => (g === "github" ? full(id) : id);
  const catalog = (g: Group) => (g === "github" ? info.catalog.repos : g === "jira" ? info.catalog.jira : info.catalog.slack);

  /** Ids shown for a group: the catalog plus anything in the draft. Repos are keyed by bare name. */
  const items = (g: Group) => {
    if (!draft) return [];
    const bare = (r: string) => (g === "github" && owner && r.startsWith(`${owner}/`) ? r.slice(owner.length + 1) : r);
    return [...new Set([...catalog(g).map(bare), ...list(draft, g)])];
  };

  const toggle = (g: Group, id: string) => {
    if (!draft) return;
    setError("");
    const cur = list(draft, g);
    if (cur.includes(id)) return setDraft(withList(draft, g, cur.filter((x) => x !== id)));
    if (g === "github" && id.includes("/")) return addRepo(id);
    setDraft(withList(draft, g, [...cur, id]));
  };

  function addRepo(raw: string) {
    if (!draft) return;
    const m = /^([\w.-]+)\/([\w.-]+)$/.exec(raw.trim());
    if (!m) return setError("Use the form owner/repo.");
    const [, o, name] = m;
    if (draft.github.owner && draft.github.owner !== o) return setError(`All repositories must share one owner (${draft.github.owner}).`);
    if (draft.github.repos.includes(name)) return;
    setDraft({ ...draft, github: { owner: o, repos: [...draft.github.repos, name] } });
  }

  const add = (g: Group) => {
    if (!draft) return;
    const v = adding[g].trim();
    if (!v) return;
    setError("");
    if (g === "github") addRepo(v);
    else {
      const id = g === "jira" ? v.toUpperCase() : v;
      if (!list(draft, g).includes(id)) setDraft(withList(draft, g, [...list(draft, g), id]));
    }
    setAdding({ ...adding, [g]: "" });
  };

  const run = async (what: "save" | "sync" | "demo") => {
    setBusy(what); setError(""); setResult(null);
    try {
      if (what === "save") {
        const w = await api<WorkspaceFile>("/api/workspace", { method: "PUT", body: draft });
        setSaved(w); setDraft(w);
      } else {
        setResult(await api<SyncResult>(what === "sync" ? "/api/sync" : "/api/demo", { method: "POST" }));
      }
      await refresh();
    } catch (e) {
      setError(errText(e));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-[2px]" onMouseDown={onClose}>
      <div role="dialog" aria-label={`Connections for ${info.workspace.name}`} onMouseDown={(e) => e.stopPropagation()}
        className="fade-up flex max-h-[80vh] w-[480px] max-w-[94vw] flex-col overflow-hidden rounded-xl border border-line2 bg-bg shadow-2xl shadow-black/30">
        <div className="flex items-center border-b border-line px-5 py-3.5">
          <h2 className="font-semibold">Connections <span className="font-normal text-dim">· {info.workspace.name}</span></h2>
          <button onClick={onClose} aria-label="Close" className="ml-auto text-dim hover:text-fg"><Icon name="x" size={15} /></button>
        </div>
        <div className="space-y-5 overflow-auto px-5 py-4">
          {loadError && <p role="alert" className="text-warn">{loadError}</p>}
          {!draft && !loadError && <p className="text-dim">Loading…</p>}
          {draft && GROUPS.map((g) => {
            const on = list(draft, g.id);
            return (
              <section key={g.id}>
                <h3 className="label mb-1.5 flex items-center gap-1.5">
                  <Icon name={g.icon} size={12} />{g.title}
                  {!info.sources[g.id].token_present && <span className="normal-case tracking-normal text-warn" title="Set the token in the server environment (.env); it is never entered here">token missing</span>}
                  <span className="ml-auto normal-case tracking-normal">{on.length}</span>
                </h3>
                {g.field && (
                  <label className="mb-1.5 flex items-center gap-2 text-[11.5px] text-dim">
                    <span className="w-[68px] shrink-0">{g.field.label}</span>
                    <input value={g.id === "jira" ? draft.jira.site : draft.slack.workspace} placeholder={g.field.hint} className={field}
                      onChange={(e) => setDraft(g.id === "jira" ? { ...draft, jira: { ...draft.jira, site: e.target.value } } : { ...draft, slack: { ...draft.slack, workspace: e.target.value } })} />
                  </label>
                )}
                <ul>
                  {items(g.id).map((id) => (
                    <li key={id}>
                      <button onClick={() => toggle(g.id, id)} className="flex h-9 w-full items-center gap-2 rounded-md px-1.5 text-left hover:bg-panel">
                        <span className="font-mono text-[12.5px]">{labelOf(g.id, id)}</span>
                        {g.id === "github" && on.includes(id) && !info.indexed_repos.includes(full(id)) && <span className="text-[11px] text-warn">not synced</span>}
                        <span className="ml-auto"><Switch on={on.includes(id)} label={labelOf(g.id, id)} /></span>
                      </button>
                    </li>
                  ))}
                </ul>
                <form onSubmit={(e) => { e.preventDefault(); add(g.id); }} className="mt-1 flex gap-2">
                  <input value={adding[g.id]} onChange={(e) => setAdding({ ...adding, [g.id]: e.target.value })} placeholder={g.add} aria-label={`Add ${g.title}`} className={field} />
                  <button type="submit" aria-label={`Add to ${g.title}`} className="grid h-8 w-8 place-items-center rounded-md border border-line text-mute hover:border-line2 hover:text-fg"><Icon name="plus" size={13} /></button>
                </form>
              </section>
            );
          })}

          {error && <p role="alert" className="text-[12px] text-warn">{error}</p>}
          {result && (
            <section aria-label="Sync result">
              <h3 className={`label mb-1.5 ${result.complete ? "" : "text-warn"}`}>{result.complete ? "Sync finished" : "Finished with incomplete streams"}</h3>
              <ul className="space-y-1 text-[12px]">
                {result.summaries.map((s) => (
                  <li key={s.stream} className="flex items-baseline gap-2">
                    <span className="truncate font-mono text-[11.5px]">{s.stream}</span>
                    <span className="ml-auto shrink-0 text-dim">{s.counts?.persisted ?? 0} stored</span>
                    {!s.complete && <span className="shrink-0 text-warn" title={(s.errors ?? []).map((x) => (typeof x === "string" ? x : "error")).join("; ")}>incomplete</span>}
                  </li>
                ))}
              </ul>
              {busy === "" && result.summaries.length > 0 && <p className="mt-2 text-[11.5px] text-dim">Artifacts only appear in evidence when their repo, project or channel is switched on above and saved.</p>}
            </section>
          )}
        </div>
        <div className="flex items-center gap-2 border-t border-line px-5 py-3">
          <button onClick={() => run("sync")} disabled={!!busy || dirty} title={dirty ? "Save your changes first" : "Sync the saved workspace"}
            className="h-8 rounded-md border border-line px-3 text-[12.5px] text-mute hover:border-line2 hover:text-fg disabled:opacity-40">
            {busy === "sync" ? "Syncing…" : "Sync now"}
          </button>
          <button onClick={() => run("demo")} disabled={!!busy}
            className="h-8 rounded-md border border-line px-3 text-[12.5px] text-mute hover:border-line2 hover:text-fg disabled:opacity-40">
            {busy === "demo" ? "Loading…" : "Load demo data"}
          </button>
          <span className="ml-auto" />
          {dirty && (
            <button onClick={() => run("save")} disabled={!!busy} className="h-8 rounded-md bg-accent px-4 text-[12.5px] font-medium text-bg hover:opacity-90 disabled:opacity-40">
              {busy === "save" ? "Saving…" : "Save"}
            </button>
          )}
          <button onClick={onClose} className="h-8 rounded-md bg-fg px-4 text-[12.5px] font-medium text-bg hover:opacity-90">Done</button>
        </div>
      </div>
    </div>
  );
}
