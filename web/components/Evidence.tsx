"use client";
import { useMemo, useState } from "react";
import { useData } from "@/lib/data";
import { KINDS, KIND_COLOR, fmtDate, fmtTime, type Kind } from "@/lib/types";
import Detail from "./Detail";
import { Icon } from "./icons";
import { useWb } from "./store";

const KIND_ICON = { issue: "issue", discussion: "discussion", pr: "pr", commit: "commit" } as const;

export function KindBadge({ kind, label }: { kind: Kind; label?: string }) {
  return (
    <span className="inline-flex shrink-0 items-center gap-1 whitespace-nowrap font-mono text-[11px]" style={{ color: KIND_COLOR[kind] }}>
      <Icon name={KIND_ICON[kind]} size={12} />{label}
    </span>
  );
}

export default function Evidence() {
  const { inv, tab, setTab, hiddenKinds, toggleKind, showInferred, setShowInferred, visible, selected } = useWb();
  const { hasInferred } = useData();
  const [open, setOpen] = useState(true);
  if (!inv) return null;
  const tabs = [{ id: "timeline", label: "Timeline", key: "1" }, { id: "graph", label: "Graph", key: "2" }] as const;

  return (
    <section aria-label="Evidence" className={`flex shrink-0 flex-col border-t border-line ${open ? "h-[36%] min-h-[220px]" : ""}`}>
      <div className="flex h-10 shrink-0 items-center gap-1 px-2">
        <button onClick={() => setOpen((o) => !o)} aria-label={open ? "Collapse evidence" : "Expand evidence"} className="grid h-7 w-7 place-items-center rounded-md text-dim hover:bg-hover hover:text-fg">
          <Icon name="chevron" size={13} className={`transition-transform ${open ? "" : "-rotate-90"}`} />
        </button>
        <span className="mr-2 text-[12.5px] font-medium">Evidence <span className="font-normal text-dim">{visible.length}</span></span>
        {open && tabs.map((t) => (
          <button key={t.id} onClick={() => setTab(t.id)} aria-pressed={tab === t.id}
            className={`h-7 rounded-md px-2.5 text-[12px] ${tab === t.id ? "bg-raised text-fg" : "text-dim hover:text-mute"}`}>{t.label}</button>
        ))}
        {open && (
          <div className="ml-auto flex items-center gap-0.5">
            {KINDS.map((k) => {
              const off = hiddenKinds.includes(k.kind);
              return (
                <button key={k.kind} onClick={() => toggleKind(k.kind)} aria-pressed={!off} aria-label={`${k.label}s`} title={`${off ? "Show" : "Hide"} ${k.label.toLowerCase()}s`}
                  className="grid h-7 w-6 place-items-center rounded-md hover:bg-hover">
                  <i className="h-2.5 w-2.5 rounded-full" style={off ? { border: "1.5px solid var(--line2)" } : { background: k.color }} />
                </button>
              );
            })}
            {hasInferred && (
              <label title="Show inferred links (dashed)" className="ml-1.5 flex h-7 cursor-pointer items-center gap-1.5 whitespace-nowrap rounded-md px-1.5 text-[11.5px] text-dim hover:bg-hover hover:text-mute">
                <input type="checkbox" checked={showInferred} onChange={(e) => setShowInferred(e.target.checked)} className="accent-[var(--warn)]" />inferred
              </label>
            )}
          </div>
        )}
      </div>
      {open && (
        <div className={`grid min-h-0 flex-1 border-t border-line ${selected ? "grid-cols-[minmax(0,1fr)_minmax(0,46%)]" : ""}`}>
          <div className="min-h-0 overflow-auto">
            {visible.length === 0 ? <p className="p-6 text-center text-dim">Nothing to show. Check the filters or connections.</p> : tab === "timeline" ? <Timeline /> : <Graph />}
          </div>
          {selected && <div className="min-h-0 overflow-hidden border-l border-line"><Detail /></div>}
        </div>
      )}
    </section>
  );
}

function useDim() {
  const { lit, selected } = useWb();
  const focus = new Set(lit);
  if (selected) focus.add(selected);
  return (id: string) => focus.size > 0 && !focus.has(id);
}

function Timeline() {
  const { visible, selected, selectNode, hoverNodes, lit } = useWb();
  const { byId } = useData();
  const dim = useDim();
  return (
    <ol className="p-2">
      {visible.map((id) => {
        const n = byId[id];
        const on = selected === id;
        return (
          <li key={id}>
            <button onClick={() => selectNode(on ? null : id)} onMouseEnter={() => hoverNodes([id])} onMouseLeave={() => hoverNodes([])} data-node={id}
              className={`flex h-9 w-full items-center gap-3 rounded-md px-2.5 text-left transition-colors ${on ? "bg-raised" : lit.has(id) ? "bg-hover" : "hover:bg-panel"} ${dim(id) ? "opacity-40" : ""}`}>
              <span className="w-[74px] shrink-0 font-mono text-[11px] text-dim">{fmtDate(n.time).slice(0, 6)}</span>
              <span className="w-[92px] shrink-0"><KindBadge kind={n.kind} label={n.ref.length > 11 ? n.ref.slice(0, 10) + "…" : n.ref} /></span>
              <span className="truncate">{n.title}</span>
              <span className="ml-auto shrink-0 font-mono text-[11px] text-dim">{n.author} {fmtTime(n.time)}</span>
            </button>
          </li>
        );
      })}
    </ol>
  );
}

const LANES: Kind[] = ["issue", "discussion", "pr", "commit"];
const LANE = 62;
const LABELS: Record<Kind, string> = { issue: "Issues", discussion: "Discussions", pr: "PRs", commit: "Commits" };

function Graph() {
  const { inv, visible, selected, selectNode, hoverNodes, lit, showInferred } = useWb();
  const { byId, edges: allEdges, hasInferred } = useData();
  const dim = useDim();
  const pos = useMemo(() => {
    const p: Record<string, { x: number; y: number }> = {};
    visible.forEach((id, i) => { p[id] = { x: 100 + i * 84, y: 28 + LANES.indexOf(byId[id].kind) * LANE }; });
    return p;
  }, [visible, byId]);
  const width = 100 + visible.length * 84;
  const edges = allEdges.filter((e) => pos[e.from] && pos[e.to] && (showInferred || e.rel !== "INFERRED"));
  const focus = new Set(lit); if (selected) focus.add(selected);

  return (
    <div className="p-2">
      <svg viewBox={`0 0 ${width} ${LANES.length * LANE + 8}`} className="block w-full" role="img" aria-label={`Evidence graph for: ${inv!.question}`}>
        {LANES.map((k, i) => (
          <g key={k}>
            <rect x={0} y={i * LANE} width={width} height={LANE - 2} rx={6} fill={i % 2 ? "transparent" : "var(--gridline)"} />
            <text x={10} y={i * LANE + 32} fill="var(--dim)" fontSize={11}>{LABELS[k]}</text>
          </g>
        ))}
        {edges.map((e, i) => {
          const a = pos[e.from], b = pos[e.to];
          const mx = (a.x + b.x) / 2;
          const on = (focus.has(e.from) && focus.has(e.to)) || (selected && (e.from === selected || e.to === selected));
          const inferred = e.rel === "INFERRED";
          return (
            <path key={i} d={`M${a.x},${a.y} C${mx},${a.y} ${mx},${b.y} ${b.x},${b.y}`} fill="none"
              stroke={on ? "var(--accent)" : inferred ? "var(--warn)" : "var(--line2)"} strokeWidth={on ? 1.8 : 1.2}
              strokeDasharray={inferred ? "4 4" : undefined} opacity={focus.size && !on ? 0.35 : 1}>
              <title>{inferred ? `inferred: ${e.why}` : e.rel}</title>
            </path>
          );
        })}
        {visible.map((id) => {
          const n = byId[id], { x, y } = pos[id];
          const on = selected === id;
          return (
            <g key={id} transform={`translate(${x},${y})`} className="cursor-pointer" opacity={dim(id) ? 0.5 : 1}
              onClick={() => selectNode(on ? null : id)} onMouseEnter={() => hoverNodes([id])} onMouseLeave={() => hoverNodes([])}
              tabIndex={0} role="button" aria-label={`${n.ref} ${n.title}`}
              onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && selectNode(on ? null : id)}>
              <circle r={on ? 14 : lit.has(id) ? 12 : 10} fill="none" stroke={KIND_COLOR[n.kind]} strokeOpacity={on ? 0.9 : 0.35} strokeWidth={on ? 2 : 1} />
              <circle r={7} fill={KIND_COLOR[n.kind]} />
              <text y={24} textAnchor="middle" fill={on ? "var(--fg)" : "var(--mute)"} fontSize={11} fontFamily="var(--font-mono)">{n.ref.length > 10 ? n.ref.slice(0, 9) + "…" : n.ref}</text>
            </g>
          );
        })}
      </svg>
      <p className="px-1 text-[11px] text-dim">Solid: explicit link{hasInferred && <> · <span className="text-warn">dashed: inferred</span></>}</p>
    </div>
  );
}
