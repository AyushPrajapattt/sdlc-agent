"use client";
// Start an ingestion and watch it live. Status is server-side (polled by DataProvider), so a reload resumes the view.
import { useState } from "react";
import { useData } from "@/lib/data";
import { fmtDate, fmtTime, type StreamStatus, type SyncMode } from "@/lib/types";
import { Icon } from "./icons";
import { Chip, Notice, Spinner, btnGhost, btnPrimary, errText } from "./ui";

const TONE: Record<StreamStatus, "run" | "ok" | "warn" | "bad"> = { running: "run", done: "ok", incomplete: "warn", failed: "bad" };
const MODES: { id: SyncMode; label: string; hint: string }[] = [
  { id: "standard", label: "Standard", hint: "up to 20 pages per stream" },
  { id: "deep", label: "Deep history", hint: "up to 100 pages per stream; slower" },
];

export default function SyncPanel() {
  const { ws, sync, syncLoaded, startSync, info, targets } = useData();
  const [mode, setMode] = useState<SyncMode>("standard");
  const [error, setError] = useState("");
  const [starting, setStarting] = useState(false);
  const running = sync?.state === "running";
  const hasTargets = !!targets && (targets.github.repos.length + targets.jira.projects.length + targets.slack.channels.length) > 0;

  const start = async (m: SyncMode) => {
    setStarting(true); setError("");
    try { await startSync(m); } catch (e) { setError(errText(e)); } finally { setStarting(false); }
  };
  if (!ws || !info) return null;

  const state = !sync ? "" : running ? "Running" : sync.state === "done" ? (sync.complete ? "Finished" : "Finished with incomplete streams") : sync.state === "failed" ? "Failed" : "";
  const when = sync?.finished_at ? `${fmtDate(sync.finished_at)} ${fmtTime(sync.finished_at)} UTC` : "";

  return (
    <div className="space-y-3 rounded-lg border border-line p-4">
      <fieldset disabled={running || starting} className="flex flex-wrap items-center gap-x-5 gap-y-1">
        <legend className="sr-only">Ingestion mode</legend>
        {MODES.map((m) => (
          <label key={m.id} className="flex cursor-pointer items-center gap-1.5">
            <input type="radio" name={`mode-${ws}`} checked={mode === m.id} onChange={() => setMode(m.id)} className="accent-[var(--accent)]" />
            <span className="font-medium">{m.label}</span><span className="text-[11.5px] text-dim">{m.hint}</span>
          </label>
        ))}
      </fieldset>
      <div className="flex items-center gap-2">
        <button type="button" onClick={() => start(mode)} disabled={running || starting || !hasTargets || !syncLoaded}
          title={hasTargets ? undefined : "Pick something to ingest first"} className={btnPrimary}>
          {running || starting ? <Spinner /> : <Icon name="play" size={11} />}{running ? "Ingesting…" : "Start ingestion"}
        </button>
        {!hasTargets && <span className="text-[11.5px] text-dim">Select at least one repository, project or channel first.</span>}
      </div>
      {error && <Notice tone="warn">{error}</Notice>}

      <div id="progress" aria-live="polite" className="space-y-2">
        {state && (
          <p className={`flex items-center gap-2 font-medium ${sync?.state === "failed" ? "text-bad" : running ? "text-accent" : sync?.complete ? "text-ok" : "text-warn"}`}>
            {running && <Spinner />}{state}
            <span className="font-normal text-dim">{sync?.mode === "deep" ? "deep history" : "standard"}{when && ` · ${when}`}</span>
          </p>
        )}
        {sync?.error && <Notice tone="warn">{sync.error}</Notice>}
        {sync && sync.streams.length > 0 && (
          <table className="w-full text-[12px]">
            <caption className="sr-only">Ingestion streams</caption>
            <thead>
              <tr className="label text-left">
                <th scope="col" className="py-1 pr-2 font-medium">Stream</th><th scope="col" className="px-2 font-medium">Status</th>
                <th scope="col" className="px-2 text-right font-medium">Pages</th><th scope="col" className="px-2 text-right font-medium">Fetched</th>
                <th scope="col" className="px-2 text-right font-medium">Stored</th><th scope="col" className="pl-2 text-right font-medium">Errors</th>
              </tr>
            </thead>
            <tbody>
              {sync.streams.map((s) => (
                <tr key={s.stream} className="border-t border-line align-top">
                  <th scope="row" className="max-w-[200px] truncate py-1.5 pr-2 text-left font-mono text-[11.5px] font-normal">{s.stream}</th>
                  <td className="px-2 py-1.5"><Chip tone={TONE[s.status]}>{s.status === "running" && <Spinner />}{s.status}</Chip></td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{s.pages}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{s.fetched}</td>
                  <td className="px-2 py-1.5 text-right tabular-nums">{s.persisted}</td>
                  <td className="py-1.5 pl-2 text-right tabular-nums">{s.errors.length}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
        {sync && sync.streams.some((s) => s.errors.length > 0) && (
          <ul className="space-y-0.5 text-[11.5px] text-warn">
            {sync.streams.flatMap((s) => s.errors.slice(0, 3).map((e, i) => <li key={`${s.stream}${i}`}><span className="font-mono">{s.stream}</span> · {e.stage}: {e.message}</li>))}
          </ul>
        )}
        {sync && sync.streams.length > 0 && (
          <p className="text-[12px] text-dim">
            Totals: <b className="font-medium text-fg">{sync.totals.fetched}</b> fetched · <b className="font-medium text-fg">{sync.totals.persisted}</b> stored · <b className="font-medium text-fg">{sync.totals.errors}</b> errors
            {sync.state === "done" && sync.graph && <> · graph: <b className="font-medium text-fg">{sync.graph.artifacts}</b> artifacts, <b className="font-medium text-fg">{sync.graph.edges}</b> links</>}
          </p>
        )}
        {sync?.state === "done" && !sync.complete && (
          <div className="rounded-md border border-line bg-panel p-3">
            <p className="flex items-center gap-1.5 text-warn"><Icon name="alert" size={13} />Finished with incomplete streams</p>
            <p className="mt-1 text-[11.5px] text-dim">Some streams hit the page limit or reported errors, so older history may be missing.</p>
            {sync.mode !== "deep" && <button type="button" onClick={() => start("deep")} disabled={starting} className={`${btnGhost} mt-2`}>{starting && <Spinner />}Sync deeper</button>}
          </div>
        )}
      </div>
    </div>
  );
}
