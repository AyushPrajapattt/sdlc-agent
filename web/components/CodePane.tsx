"use client";
import { BY_ID, EDGES, FILES, fmtDate, prOf } from "@/lib/data";
import { useWb } from "./store";

const PR_COLORS = ["#8b5cf6", "#14b8a6", "#f59e0b", "#f43f5e"];
const PR_ORDER = ["pr218", "pr190", "pr201"];
const stripe = (blame: string) => {
  const pr = prOf(blame);
  return pr ? PR_COLORS[PR_ORDER.indexOf(pr) % PR_COLORS.length] : "var(--line2)";
};
const explained = (blame: string) => EDGES.some((e) => e.rel !== "INFERRED" && (e.from === blame || e.to === blame));

const TOKEN = /(#.*$)|("[^"]*"|'[^']*')|(\b\d+(?:\.\d+)?\b)|\b(import|from|class|def|return|if|for|in|is|not|None|raise|and|or)\b/g;

/** Tiny Python highlighter: enough for a mock, no dependency. */
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
  const { file, line, lit, selected, selectLine, hoverNodes } = useWb();
  const f = FILES.find((x) => x.path === file)!;
  const withReason = f.lines.filter((l) => explained(l.blame)).length;

  return (
    <section className="flex min-h-0 min-w-0 flex-1 flex-col" aria-label="Code">
      <div className="flex h-10 shrink-0 items-center gap-3 border-b border-line px-4">
        <span className="font-mono text-[12.5px] font-medium">{file.split("/").pop()}</span>
        <span className="truncate text-[11.5px] text-dim">{withReason} of {f.lines.length} lines have recorded reasons</span>
        <span className="ml-auto hidden shrink-0 text-[11.5px] text-dim xl:inline">click a line to ask why</span>
      </div>

      <div className="min-h-0 flex-1 overflow-auto py-2 font-mono text-[12px] leading-[21px]">
        {f.lines.map((l, i) => {
          const n = BY_ID[l.blame];
          const isFirst = f.lines[i - 1]?.blame !== l.blame;
          const pr = prOf(l.blame);
          const reason = explained(l.blame);
          const isLit = lit.has(l.blame) || (pr ? lit.has(pr) : false) || selected === l.blame;
          const focus = line === i + 1;
          return (
            <div key={i} onClick={() => selectLine(i + 1)}
              onMouseEnter={() => hoverNodes(pr ? [l.blame, pr] : [l.blame])} onMouseLeave={() => hoverNodes([])}
              title={`${n.ref} · ${n.author} · ${fmtDate(n.time)}${pr ? ` · PR ${BY_ID[pr].ref}` : ""}${reason ? "" : " · no recorded reason"}`}
              className={`flex cursor-pointer items-stretch transition-colors ${focus ? "bg-accent/10" : isLit ? "bg-hover" : "hover:bg-panel"}`}>
              <span className="w-[3px] shrink-0" style={{ background: stripe(l.blame), opacity: reason ? (isLit || focus ? 1 : 0.7) : 0.5 }} />
              <span className={`w-[58px] shrink-0 pl-2.5 text-[11px] ${isFirst ? "text-dim" : "text-transparent"}`}>{n.ref.slice(0, 7)}</span>
              <span className={`w-8 shrink-0 select-none pr-2.5 text-right ${focus ? "text-accent" : "text-dim/60"}`}>{i + 1}</span>
              <span className="whitespace-pre pr-6">{highlight(l.text)}</span>
              {focus && (
                <span className="fade-up ml-2 whitespace-nowrap pr-4 font-sans text-[11px] italic text-dim">
                  {n.author}, {fmtDate(n.time)} · {n.title}
                </span>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex h-9 shrink-0 items-center gap-3 border-t border-line px-4 text-[11px] text-dim">
        {PR_ORDER.map((id, i) => (
          <span key={id} className="flex items-center gap-1.5 whitespace-nowrap"><i className="h-2.5 w-[3px] rounded-sm" style={{ background: PR_COLORS[i] }} />PR {BY_ID[id].ref}</span>
        ))}
        <span className="flex items-center gap-1.5 whitespace-nowrap"><i className="h-2.5 w-[3px] rounded-sm bg-line2" />no reason recorded</span>
      </div>
    </section>
  );
}
