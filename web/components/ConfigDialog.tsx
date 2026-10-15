"use client";
// "Connections": the same cards, pickers and sync panel as the setup page, plus workspace settings, in a dialog.
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { wsApi } from "@/lib/api";
import { useData } from "@/lib/data";
import { Icon } from "./icons";
import { LlmCard, Sources } from "./Integrations";
import SyncPanel from "./SyncPanel";
import { Notice, Spinner, btnGhost, btnPrimary, errText, field } from "./ui";

function Settings({ onClose }: { onClose: () => void }) {
  const router = useRouter();
  const { info, saveTargets, refreshWorkspaces } = useData();
  const [name, setName] = useState<string | null>(null);
  const [busy, setBusy] = useState<"" | "rename" | "delete">("");
  const [confirm, setConfirm] = useState(false);
  const [error, setError] = useState("");
  if (!info) return null;
  const cur = name ?? info.workspace.name;

  const rename = async () => {
    setBusy("rename"); setError("");
    try { await saveTargets({ name: cur.trim() }); await refreshWorkspaces(); setName(null); } catch (e) { setError(errText(e)); } finally { setBusy(""); }
  };
  const remove = async () => {
    setBusy("delete"); setError("");
    try { await wsApi.remove(info.workspace.slug); onClose(); router.push("/"); } catch (e) { setError(errText(e)); setBusy(""); }
  };

  return (
    <section aria-label="Workspace settings" className="space-y-2 rounded-lg border border-line p-4">
      <h3 className="label">Workspace</h3>
      <form onSubmit={(e) => { e.preventDefault(); rename(); }} className="flex items-center gap-2">
        <input value={cur} onChange={(e) => setName(e.target.value)} aria-label="Workspace name" maxLength={80} className={field} />
        <button type="submit" disabled={!!busy || !cur.trim() || cur.trim() === info.workspace.name} className={btnGhost}>{busy === "rename" && <Spinner />}Rename</button>
      </form>
      <div className="flex items-center gap-2">
        {confirm ? (
          <>
            <span className="text-[12px] text-dim">Delete this workspace and its saved credentials? Ingested graph data stays.</span>
            <button onClick={remove} disabled={!!busy} className="ml-auto inline-flex h-8 items-center gap-1.5 rounded-md bg-bad px-3 text-[12.5px] font-medium text-bg hover:opacity-90 disabled:opacity-40">{busy === "delete" && <Spinner />}Delete</button>
            <button onClick={() => setConfirm(false)} disabled={!!busy} className={btnGhost}>Cancel</button>
          </>
        ) : (
          <button onClick={() => setConfirm(true)} className="inline-flex h-8 items-center gap-1.5 rounded-md border border-line px-3 text-[12.5px] text-mute hover:border-bad hover:text-bad">Delete workspace</button>
        )}
      </div>
      {error && <Notice tone="warn">{error}</Notice>}
    </section>
  );
}

export default function ConfigDialog({ onClose }: { ws: string; onClose: () => void }) {
  const { info } = useData();
  useEffect(() => {
    const on = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, [onClose]);
  if (!info) return null;

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/40 backdrop-blur-[2px]" onMouseDown={onClose}>
      <div role="dialog" aria-label={`Connections for ${info.workspace.name}`} onMouseDown={(e) => e.stopPropagation()}
        className="fade-up flex max-h-[86vh] w-[640px] max-w-[94vw] flex-col overflow-hidden rounded-xl border border-line2 bg-bg shadow-2xl shadow-black/30">
        <div className="flex items-center border-b border-line px-5 py-3.5">
          <h2 className="font-semibold">Connections <span className="font-normal text-dim">· {info.workspace.name}</span></h2>
          <button onClick={onClose} aria-label="Close" className="ml-auto text-dim hover:text-fg"><Icon name="x" size={15} /></button>
        </div>
        <div className="space-y-5 overflow-auto px-5 py-4">
          <section aria-label="Sources"><h3 className="label mb-2">Sources</h3><Sources /></section>
          <section aria-label="AI model"><h3 className="label mb-2">AI model</h3><LlmCard /></section>
          <section aria-label="Ingestion"><h3 className="label mb-2">Ingestion</h3><SyncPanel /></section>
          <Settings onClose={onClose} />
        </div>
        <div className="flex items-center gap-2 border-t border-line px-5 py-3">
          <span className="ml-auto" />
          <button onClick={onClose} className={btnPrimary}>Done</button>
        </div>
      </div>
    </div>
  );
}
