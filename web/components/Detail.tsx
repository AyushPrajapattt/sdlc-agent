"use client";
import Link from "next/link";
import { BY_ID, EDGES, fmtDate } from "@/lib/data";
import { FILE_PATHS } from "@/lib/workspace";
import { KindBadge } from "./Evidence";
import { Icon } from "./icons";
import { useWb } from "./store";

function Quoted({ text, quotes }: { text: string; quotes: string[] }) {
  const hit = quotes.map((q) => ({ q, i: text.toLowerCase().indexOf(q.toLowerCase()) })).find((x) => x.i >= 0);
  if (!hit) return <>{text}</>;
  return <>{text.slice(0, hit.i)}<mark className="quote">{text.slice(hit.i, hit.i + hit.q.length)}</mark>{text.slice(hit.i + hit.q.length)}</>;
}

export default function Detail() {
  const { inv, selected, selectNode, claim, showInferred, base, locked } = useWb();
  const n = selected ? BY_ID[selected] : null;
  if (!n || !inv) return null;

  const quotes = inv.claims.filter((c) => c.id === claim).flatMap((c) => c.cites.filter((x) => x.node === n.id && x.quote).map((x) => x.quote!));
  const rels = EDGES.filter((e) => (e.from === n.id || e.to === n.id) && (showInferred || e.rel !== "INFERRED"));

  return (
    <div className="fade-up flex h-full flex-col" key={n.id}>
      <div className="flex h-10 shrink-0 items-center gap-2 border-b border-line px-3">
        <KindBadge kind={n.kind} label={n.ref} />
        <span className="truncate font-medium">{n.title}</span>
        <a href={n.url} target="_blank" rel="noopener noreferrer" aria-label="Open source" title="Open source" className="ml-auto shrink-0 text-dim hover:text-accent"><Icon name="ext" size={13} /></a>
        <button onClick={() => selectNode(null)} aria-label="Close" className="shrink-0 text-dim hover:text-fg"><Icon name="x" size={14} /></button>
      </div>
      <div className="min-h-0 flex-1 overflow-auto p-3">
        <div className="mb-2 font-mono text-[11px] text-dim">{n.author} · {fmtDate(n.time)}</div>
        <p className="whitespace-pre-wrap text-[12.5px] leading-relaxed"><Quoted text={n.text} quotes={quotes} /></p>

        {rels.length > 0 && (
          <div className="mt-4">
            <div className="label mb-1.5">Linked</div>
            <div className="flex flex-wrap gap-1">
              {rels.map((e, i) => {
                const o = BY_ID[e.from === n.id ? e.to : e.from];
                const inferred = e.rel === "INFERRED";
                return locked(o.id) ? null : (
                  <button key={i} onClick={() => selectNode(o.id)} title={inferred ? `Inferred: ${e.why}` : e.rel}
                    className={`rounded border px-1.5 py-0.5 hover:bg-hover ${inferred ? "border-dashed border-warn/60" : "border-line"}`}>
                    <KindBadge kind={o.kind} label={o.ref} />
                  </button>
                );
              })}
            </div>
          </div>
        )}
        {n.paths && (
          <div className="mt-4">
            <div className="label mb-1.5">Files</div>
            <div className="flex flex-wrap gap-1">
              {n.paths.filter((p) => FILE_PATHS.includes(p)).map((p) => (
                <Link key={p} href={`${base}/f/${p}`} className="rounded border border-line px-1.5 py-0.5 font-mono text-[11px] text-mute hover:border-line2 hover:text-fg">{p.split("/").pop()}</Link>
              ))}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
