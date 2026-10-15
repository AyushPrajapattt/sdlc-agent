"use client";
import { useMemo } from "react";
import { useData } from "@/lib/data";
import { fmtDate } from "@/lib/types";
import Empty from "./Empty";
import { useWb } from "./store";

const PR_COLORS = ["#8b5cf6", "#14b8a6", "#f59e0b", "#f43f5e"];

const TOKEN = /(#.*$)|("[^"]*"|'[^']*')|(\b\d+(?:\.\d+)?\b)|\b(import|from|class|def|return|if|for|in|is|not|None|raise|and|or)\b/g;

/** Tiny Python highlighter, no dependency; other languages render plain. */
function highlight(src: string) {
  const out: React.ReactNode[] = [];
  let last = 0, m: RegExpExecArray | null;
  TOKEN.lastIndex = 0;
  while ((m = TOKEN.exec(src))) {
    if (m.index > last) out.push(src.slice(last, m.index));
    const cls = m[1] ? "text-dim italic" : m[2] ? "text-ok" : m[3] ? "text-warn" : "text-accent";
    out.push(<span key={m.index} className={cls}>{m[0]}</span>);
    last = m.index + m[0].length;
  }
  out.push(src.slice(last));
  return out;
}

export default function CodePane() {
  const { file, code, line, lit, selected, selectLine, hoverNodes } = useWb();
  const { byId, explained, prOf } = useData();
  const lines = useMemo(() => code.data?.lines ?? [], [code.data]);
  // PRs in order of first appearance, so each gets a stable stripe colour within the file
  const prs = useMemo(() => [...new Set(lines.map((l) => (l.blame ? prOf(l.blame) : undefined)).filter((x): x is string => !!x && !!byId[x]))], [lines, prOf, byId]);
  const stripe = (blame: string | null) => {
    const pr = blame ? prOf(blame) : undefined;
    return pr && prs.includes(pr) ? PR_COLORS[prs.indexOf(pr) % PR_COLORS.length] : "var(--line2)";
  };

  if (!file) return <section className="flex min-h-0 min-w-0 flex-1 flex-col" aria-label="Code"><Empty icon="file" title="This question is not tied to a file" /></section>;
  if (code.loading) return <section className="flex min-h-0 min-w-0 flex-1 flex-col" aria-label="Code"><Empty icon="file" title="Loading…" /></section>;
  if (code.error || !code.data) return <section className="flex min-h-0 min-w-0 flex-1 flex-col" aria-label="Code"><Empty icon="alert" title="Could not load this file"><p className="text-dim">{code.error || "No data"}</p></Empty></section>;
  const withReason = lines.filter((l) => l.blame && explained(l.blame)).length;

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col" aria-label="Code">
      <div className="flex h-10 shrink-0 items-center gap-3 border-b border-line px-4">
        <span className="font-mono text-[12.5px] font-medium">{file.split("/").pop()}</span>
        <span className="truncate text-[11.5px] text-dim">{withReason} of {lines.length} lines have recorded reasons</span>
        {!code.data.complete && <span className="truncate text-[11.5px] text-warn" title={code.data.note}>Blame incomplete{code.data.note ? `: ${code.data.note}` : ""}</span>}
        <span className="ml-auto hidden shrink-0 text-[11.5px] text-dim xl:inline">click a line to ask why</span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto py-2 font-mono text-[12px] leading-[21px]">
        {lines.map((l, i) => {
          const n = l.blame ? byId[l.blame] : undefined;
          const isFirst = lines[i - 1]?.blame !== l.blame;
          const pr = l.blame ? prOf(l.blame) : undefined;
          const reason = !!l.blame && explained(l.blame);
          const isLit = !!l.blame && (lit.has(l.blame) || (pr ? lit.has(pr) : false) || selected === l.blame);
          const focus = line === i + 1;
          return (
            <div key={i} onClick={() => selectLine(i + 1)}
              onMouseEnter={() => hoverNodes(l.blame ? (pr ? [l.blame, pr] : [l.blame]) : [])} onMouseLeave={() => hoverNodes([])}
              title={n ? `${n.ref} · ${n.author} · ${fmtDate(n.time)}${pr && byId[pr] ? ` · PR ${byId[pr].ref}` : ""}${reason ? "" : " · no recorded reason"}` : "No recorded origin"}
              className={`flex cursor-pointer items-stretch transition-colors ${focus ? "bg-accent/10" : isLit ? "bg-hover" : "hover:bg-panel"}`}>
              <span className="w-[3px] shrink-0" style={{ background: stripe(l.blame), opacity: reason ? (isLit || focus ? 1 : 0.7) : 0.5 }} />
              <span className={`w-[58px] shrink-0 pl-2.5 text-[11px] ${isFirst ? "text-dim" : "text-transparent"}`}>{n?.ref.slice(0, 7)}</span>
              <span className={`w-8 shrink-0 select-none pr-2.5 text-right ${focus ? "text-accent" : "text-dim/60"}`}>{i + 1}</span>
              <span className="whitespace-pre pr-6">{file.endsWith(".py") ? highlight(l.text) : l.text}</span>
              {focus && n && (
                <span className="fade-up ml-2 whitespace-nowrap pr-4 font-sans text-[11px] italic text-dim">
                  {n.author}, {fmtDate(n.time)} · {n.title}
                </span>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex h-9 shrink-0 items-center gap-3 border-t border-line px-4 text-[11px] text-dim">
        {prs.slice(0, PR_COLORS.length).map((id, i) => (
          <span key={id} className="flex items-center gap-1.5 whitespace-nowrap"><i className="h-2.5 w-[3px] rounded-sm" style={{ background: PR_COLORS[i] }} />PR {byId[id].ref}</span>
        ))}
        <span className="flex items-center gap-1.5 whitespace-nowrap"><i className="h-2.5 w-[3px] rounded-sm bg-line2" />no reason recorded</span>
      </div>
    </section>
  );
}
