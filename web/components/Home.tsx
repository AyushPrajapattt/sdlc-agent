"use client";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { wsApi } from "@/lib/api";
import { useData } from "@/lib/data";
import { fmtDate, fmtTime, type WorkspaceRow } from "@/lib/types";
import Empty from "./Empty";
import { Icon } from "./icons";
import { Chip, Notice, Spinner, btnGhost, btnPrimary, errText, field } from "./ui";

function SyncLine({ s }: { s: WorkspaceRow["last_sync"] }) {
  if (!s) return <span className="text-dim">Not synced yet</span>;
  const tone = s.state === "done" ? "text-ok" : s.state === "failed" ? "text-bad" : s.state === "running" ? "text-accent" : "text-dim";
  return (
    <span className="text-dim">
      Last sync <span className={tone}>{s.state}</span>
      {s.finished_at && ` · ${fmtDate(s.finished_at)} ${fmtTime(s.finished_at)} UTC`}
    </span>
  );
}

function Card({ w, onDeleted }: { w: WorkspaceRow; onDeleted: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const stats = [
    { icon: "repo", n: w.connected.repos, label: w.connected.repos === 1 ? "repo" : "repos" },
    { icon: "issue", n: w.connected.jira, label: "Jira" },
    { icon: "discussion", n: w.connected.slack, label: "Slack" },
  ] as const;
  const empty = stats.every((s) => s.n === 0);

  const remove = async () => {
    setBusy(true); setError("");
    try { await wsApi.remove(w.slug); onDeleted(); } catch (e) { setError(errText(e)); setBusy(false); }
  };

  return (
    <li className="card flex flex-col p-5">
      <div className="flex items-center gap-3">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-fg text-[15px] font-semibold text-bg">{w.name[0]?.toUpperCase()}</span>
        <h2 className="min-w-0 truncate text-[15px] font-semibold">{w.name}</h2>
        {w.demo && <Chip tone="dim"><Icon name="flask" size={11} />demo</Chip>}
      </div>
      <div className="mt-4 flex gap-4 text-[12.5px]">
        {empty ? <span className="text-dim">Nothing connected yet</span> : stats.map((s) => (
          <span key={s.label} className={`flex items-center gap-1.5 ${s.n ? "text-mute" : "text-dim/60"}`}>
            <Icon name={s.icon} size={13} /><b className="font-medium text-fg">{s.n}</b>{s.label}
          </span>
        ))}
      </div>
      <p className="mt-2 text-[12px]"><SyncLine s={w.last_sync} /></p>
      <div className="mt-5 flex items-center gap-2">
        <Link href={`/w/${w.slug}`} className={btnPrimary}>Open</Link>
        <Link href={`/w/${w.slug}/setup`} className={btnGhost}><Icon name="sliders" size={13} />Set up</Link>
        {confirm ? (
          <span className="ml-auto flex items-center gap-1.5 text-[12px]">
            <span className="text-dim">Delete?</span>
            <button onClick={remove} disabled={busy} className="inline-flex h-8 items-center gap-1.5 rounded-md bg-bad px-3 text-[12.5px] font-medium text-bg hover:opacity-90 disabled:opacity-40">{busy && <Spinner />}Delete</button>
            <button onClick={() => setConfirm(false)} disabled={busy} className={btnGhost}>Cancel</button>
          </span>
        ) : (
          <button onClick={() => setConfirm(true)} aria-label={`Delete workspace ${w.name}`} className="ml-auto grid h-8 w-8 place-items-center rounded-md text-dim hover:bg-hover hover:text-bad"><Icon name="x" size={14} /></button>
        )}
      </div>
      {error && <div className="mt-2"><Notice tone="warn">{error}</Notice></div>}
    </li>
  );
}

export default function Home() {
  const router = useRouter();
  const { workspaces, workspacesError, refreshWorkspaces } = useData();
  const [name, setName] = useState("");
  const [busy, setBusy] = useState<"" | "create" | "demo">("");
  const [error, setError] = useState("");

  const create = async (demo: boolean) => {
    const n = demo ? "Acme Demo" : name.trim();
    if (!n) return;
    setBusy(demo ? "demo" : "create"); setError("");
    try {
      const w = await wsApi.create(n, demo);
      router.push(`/w/${w.slug}/setup${demo ? "?auto=1" : ""}`);
    } catch (e) { setError(errText(e)); setBusy(""); }
  };

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-[760px] px-8 pb-16 pt-16">
        <h1 className="text-[24px] font-semibold tracking-tight">Workspaces</h1>
        <p className="mt-1 text-dim">Each workspace has its own sources, credentials and AI model.</p>

        <div className="card mt-8 flex flex-wrap items-center gap-3 p-4">
          <form onSubmit={(e) => { e.preventDefault(); create(false); }} className="flex min-w-[260px] flex-1 items-center gap-2">
            <input value={name} onChange={(e) => setName(e.target.value)} placeholder="New workspace name" aria-label="New workspace name" maxLength={80} className={field} />
            <button type="submit" disabled={!!busy || !name.trim()} className={btnGhost}>{busy === "create" ? <Spinner /> : <Icon name="plus" size={13} />}Create workspace</button>
          </form>
          <button onClick={() => create(true)} disabled={!!busy} className={btnPrimary}>{busy === "demo" ? <Spinner /> : <Icon name="flask" size={13} />}Try the demo workspace</button>
          {error && <div className="w-full"><Notice tone="warn">{error}</Notice></div>}
        </div>

        <div className="mt-6">
          {workspacesError && (
            <Empty icon="alert" title="Backend unavailable">
              <p className="mb-3 max-w-[360px] text-dim">{workspacesError}</p>
              <button onClick={refreshWorkspaces} className={btnPrimary}>Retry</button>
            </Empty>
          )}
          {!workspacesError && !workspaces && <p className="flex items-center gap-2 text-dim"><Spinner />Loading…</p>}
          {workspaces && workspaces.length === 0 && (
            <div className="py-10"><Empty icon="repo" title="No workspaces yet">
              <p className="max-w-[360px] text-dim">Create one above, or try the demo workspace to see the product with sample data.</p>
            </Empty></div>
          )}
          {workspaces && workspaces.length > 0 && (
            <ul className="grid grid-cols-2 gap-4">{workspaces.map((w) => <Card key={w.slug} w={w} onDeleted={refreshWorkspaces} />)}</ul>
          )}
        </div>
      </div>
    </div>
  );
}
