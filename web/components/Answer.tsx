"use client";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import { lockedReason, useData } from "@/lib/data";
import type { Claim, Status, Step } from "@/lib/types";
import { KindBadge } from "./Evidence";
import { Icon, type IconName } from "./icons";
import { useWb } from "./store";

const ST: Record<Status, { label: string; color: string; icon: IconName }> = {
  supported: { label: "Supported", color: "var(--ok)", icon: "check" },
  inferred: { label: "Inferred", color: "var(--warn)", icon: "spark" },
  unknown: { label: "Unknown", color: "var(--unk)", icon: "help" },
};
const STEP_ICON: Record<string, IconName> = { understand: "help", plan: "list", tool: "search", gap: "alert", synthesize: "spark" };

/** Rows of investigations in a repo. Used standalone (repo page) and in the picker popover. */
export function InvestigationList({ base, current }: { base: string; current?: string }) {
  const { investigations } = useData();
  if (!investigations.length) return <p className="px-3 text-[12px] text-dim">No questions yet. Ask one below, or click a line with a coloured stripe.</p>;
  return (
    <ul className="space-y-1">
      {investigations.map((i) => (
        <li key={i.id}>
          <Link href={`${base}/why/${i.id}`} className={`block rounded-lg border px-3 py-2.5 ${current === i.id ? "border-line2 bg-raised" : "border-transparent hover:bg-hover"}`}>
            <div className="font-medium leading-snug">{i.question}</div>
            {i.file && <div className="mt-0.5 font-mono text-[11px] text-dim">{i.file.split("/").pop()}{i.line ? `:${i.line}` : ""}</div>}
          </Link>
        </li>
      ))}
    </ul>
  );
}

function Picker() {
  const { inv, base } = useWb();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const on = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", on);
    return () => document.removeEventListener("mousedown", on);
  }, []);
  return (
    <div ref={ref} className="relative min-w-0 flex-1">
      <button onClick={() => setOpen((o) => !o)} aria-expanded={open} className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-left hover:bg-hover">
        <Icon name="help" size={13} className="shrink-0 text-dim" />
        <span className="truncate font-medium">{inv ? inv.question : "Investigations"}</span>
        <Icon name="updown" size={12} className="ml-auto shrink-0 text-dim" />
      </button>
      {open && (
        <div className="fade-up absolute inset-x-0 top-9 z-30 rounded-lg border border-line2 bg-bg p-1.5 shadow-xl shadow-black/20" onClick={() => setOpen(false)}>
          <InvestigationList base={base} current={inv?.id} />
        </div>
      )}
    </div>
  );
}

export default function Answer() {
  const { inv, base, running, ask, askError, provider, setProvider } = useWb();
  const { info } = useData();
  const [q, setQ] = useState(useSearchParams().get("q") ?? ""); // the setup page's suggested questions arrive as ?q=
  const providers = (info?.providers ?? []).filter((p) => p.configured);

  const submit = (e: { preventDefault(): void }) => {
    e.preventDefault();
    const question = q.trim();
    if (!question || running) return;
    ask(question);
    setQ("");
  };

  return (
    <aside className="flex h-full min-w-0 flex-col border-l border-line" aria-label="Answer">
      <div className="flex h-10 shrink-0 items-center border-b border-line px-2"><Picker /></div>
      <div className="min-h-0 flex-1 overflow-auto">
        {running ? <LiveBody /> : inv ? <Body key={inv.id} /> : (
          <div className="p-3">
            <InvestigationList base={base} />
            <p className="mt-4 px-3 text-[12px] text-dim">Or click a line with a coloured stripe.</p>
          </div>
        )}
      </div>
      <form onSubmit={submit} className="shrink-0 p-3 pt-1">
        <div className="flex items-center gap-2 rounded-lg border border-line bg-bg px-2.5 focus-within:border-line2">
          <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Ask why…" aria-label="Ask why" maxLength={8000} disabled={running}
            className="h-9 min-w-0 flex-1 bg-transparent text-[13px] outline-none placeholder:text-dim" />
          {providers.length > 1 && (
            <select value={provider} onChange={(e) => setProvider(e.target.value)} aria-label="Provider" disabled={running}
              className="h-6 max-w-[90px] rounded bg-transparent text-[11px] text-dim outline-none hover:text-fg">
              <option value="">default</option>
              {providers.map((p) => <option key={p.name} value={p.name}>{p.name}</option>)}
            </select>
          )}
          <button type="submit" aria-label="Ask" disabled={running} className="text-dim hover:text-accent disabled:opacity-40"><Icon name="corner" size={14} /></button>
        </div>
        {askError && <p role="alert" className="mt-1 text-[11.5px] text-warn">{askError}</p>}
      </form>
    </aside>
  );
}

function Fold({ title, count, children }: { title: string; count?: number | string; children: ReactNode }) {
  return (
    <details className="group border-t border-line">
      <summary className="flex h-10 cursor-pointer list-none items-center gap-2 text-[12.5px] text-mute hover:text-fg">
        <Icon name="chevron" size={11} className="text-dim transition-transform group-not-open:-rotate-90" />
        {title}{count !== undefined && <span className="text-dim">{count}</span>}
      </summary>
      <div className="pb-3 pl-5">{children}</div>
    </details>
  );
}

function Body() {
  const { inv, step, replay } = useWb();
  if (!inv) return null;
  const done = step >= inv.trace.length;
  const shown = inv.claims.filter((c) => step > c.afterStep);
  const n = (s: Status) => inv.claims.filter((c) => c.status === s).length;

  return (
    <div className="px-4 pb-4 pt-3">
      {done ? (
        <div className="fade-up">
          <p className="text-[13.5px] leading-relaxed">{inv.summary}</p>
          <div className="mt-2.5 flex gap-3 text-[11.5px] text-dim">
            {(Object.keys(ST) as Status[]).map((s) => (
              <span key={s} className="flex items-center gap-1.5"><i className="h-1.5 w-1.5 rounded-full" style={{ background: ST[s].color }} />{n(s)} {s}</span>
            ))}
          </div>
        </div>
      ) : (
        <p className="pulse2 flex items-center gap-2 text-mute" role="status"><Icon name="spark" size={13} className="text-accent" />Investigating · {step + 1}/{inv.trace.length}</p>
      )}

      <ul className="mt-4 divide-y divide-line border-y border-line">{shown.map((c) => <ClaimRow key={c.id} c={c} />)}</ul>

      {done && (
        <div className="mt-1">
          <Fold title="Gaps" count={inv.gaps.length}>
            <ul className="space-y-1.5 text-mute">{inv.gaps.map((g) => <li key={g} className="flex gap-2"><span className="text-dim">·</span>{g}</li>)}</ul>
          </Fold>
          <Fold title="Still valid?" count={inv.checks.length}>
            <ul className="space-y-2">
              {inv.checks.map((c) => (
                <li key={c.label} className="flex gap-2">
                  <i className="mt-[7px] h-1.5 w-1.5 shrink-0 rounded-full" style={{ background: c.state === "holds" ? "var(--ok)" : c.state === "changed" ? "var(--bad)" : "var(--unk)" }} />
                  <div><div>{c.label}</div><div className="text-[11.5px] text-dim">{c.detail}</div></div>
                </li>
              ))}
            </ul>
          </Fold>
        </div>
      )}
      <Fold title="Trace" count={inv.trace.length}>
        <button onClick={replay} className="mb-2 flex items-center gap-1 text-[12px] text-accent hover:underline"><Icon name="replay" size={11} />Replay <span className="kbd">r</span></button>
        <TraceList trace={inv.trace} step={step} />
      </Fold>
    </div>
  );
}

function TraceList({ trace, step }: { trace: Step[]; step: number }) {
  return (
    <ol className="space-y-1.5">
      {trace.map((s, i) => {
        const state = i < step ? "done" : i === step ? "active" : "pending";
        return (
          <li key={i} className={`flex items-start gap-2 ${state === "pending" ? "opacity-40" : ""}`}>
            <span className={`mt-0.5 grid h-4 w-4 shrink-0 place-items-center rounded-full ${state === "done" ? "bg-ok/15 text-ok" : state === "active" ? "pulse2 bg-accent/20 text-accent" : "bg-line text-dim"}`}>
              <Icon name={state === "done" ? "check" : STEP_ICON[s.kind]} size={9} />
            </span>
            <div className="min-w-0"><div className={s.kind === "tool" ? "font-mono text-[12px]" : ""}>{s.label}</div><div className="text-[11.5px] text-dim">{s.detail}</div></div>
          </li>
        );
      })}
    </ol>
  );
}

/** Steps streamed from /api/investigate as they happen; the claims arrive with the final event. */
function LiveBody() {
  const { live } = useWb();
  return (
    <div className="px-4 pb-4 pt-3">
      <p className="pulse2 flex items-center gap-2 text-mute" role="status"><Icon name="spark" size={13} className="text-accent" />Investigating · {live.length} step{live.length === 1 ? "" : "s"}</p>
      <div className="mt-3"><TraceList trace={live} step={live.length} /></div>
    </div>
  );
}

function ClaimRow({ c }: { c: Claim }) {
  const { claim, setClaim, hoverNodes, selectNode, feedback, vote, locked } = useWb();
  const { byId } = useData();
  const active = claim === c.id;
  const v = feedback[c.id];
  const s = ST[c.status];
  return (
    <li onMouseEnter={() => hoverNodes(c.cites.map((x) => x.node))} onMouseLeave={() => hoverNodes([])} className={`fade-up py-2.5 ${active ? "bg-panel -mx-4 px-4" : ""}`}>
      <div className="flex gap-2.5">
        <span className="mt-[3px] shrink-0" style={{ color: s.color }}><Icon name={s.icon} size={14} /></span>
        <div className="min-w-0 flex-1">
          <button onClick={() => setClaim(active ? null : c.id)} aria-expanded={active} className={`block text-left leading-snug ${v === "disputed" ? "text-dim line-through" : ""}`}>
            {c.status !== "supported" && <span className="mr-1.5 text-[11px] font-medium" style={{ color: s.color }}>{s.label}</span>}{c.text}
          </button>
          <div className="mt-1.5 flex flex-wrap gap-1">
            {c.cites.map((x, i) => {
              const n = byId[x.node];
              if (!n) return null; // cited node missing from the loaded graph
              return locked(x.node) ? (
                <span key={i} title={`${lockedReason(n)} is not connected`} className="flex items-center gap-1 rounded border border-dashed border-line2 px-1.5 py-0.5 text-[11px] text-dim"><Icon name="lock" size={10} />{lockedReason(n)}</span>
              ) : (
                <button key={i} onClick={() => { setClaim(c.id); selectNode(x.node); }} className="rounded border border-line px-1.5 py-0.5 hover:border-line2 hover:bg-hover">
                  <KindBadge kind={n.kind} label={n.ref} />
                </button>
              );
            })}
          </div>
          {active && (
            <div className="fade-up mt-2 text-[12px] text-dim">
              {c.note && <p className="mb-2">{c.note}</p>}
              <div className="flex gap-1.5">
                {(["confirmed", "disputed"] as const).map((k) => (
                  <button key={k} onClick={() => vote(c.id, k)} aria-pressed={v === k}
                    className={`h-6 rounded-md border px-2 text-[11.5px] ${v === k ? (k === "confirmed" ? "border-ok/50 text-ok" : "border-bad/50 text-bad") : "border-line hover:border-line2 hover:text-fg"}`}>
                    {k === "confirmed" ? "Looks right" : "Wrong"}
                  </button>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>
    </li>
  );
}
