"use client";
import Link from "next/link";
import { useData } from "@/lib/data";
import { Ready } from "./Gate";
import { Icon } from "./icons";
import { useManage } from "./Shell";

function Card() {
  const { info, connected } = useData();
  const manage = useManage();
  if (!info) return null;
  const w = info.workspace;
  const stats = [
    { icon: "repo", n: connected.repos.length, label: connected.repos.length === 1 ? "repo" : "repos" },
    { icon: "issue", n: connected.jira.length, label: "Jira" },
    { icon: "discussion", n: connected.slack.length, label: "Slack" },
  ] as const;
  const empty = stats.every((s) => s.n === 0);

  return (
    <li className="card flex flex-col p-5">
      <div className="flex items-center gap-3">
        <span className="grid h-9 w-9 place-items-center rounded-lg bg-fg text-[15px] font-semibold text-bg">{w.name[0]}</span>
        <h2 className="text-[15px] font-semibold">{w.name}</h2>
      </div>
      <div className="mt-4 flex gap-4 text-[12.5px]">
        {empty ? <span className="text-dim">Nothing connected yet</span> : stats.map((s) => (
          <span key={s.label} className={`flex items-center gap-1.5 ${s.n ? "text-mute" : "text-dim/60"}`}>
            <Icon name={s.icon} size={13} /><b className="font-medium text-fg">{s.n}</b>{s.label}
          </span>
        ))}
      </div>
      <div className="mt-5 flex gap-2">
        <Link href={`/w/${w.slug}`} className="flex h-8 items-center rounded-md bg-fg px-4 text-[12.5px] font-medium text-bg hover:opacity-90">Open</Link>
        <button onClick={() => manage(w.slug)} className="flex h-8 items-center gap-1.5 rounded-md border border-line px-3 text-[12.5px] text-mute hover:border-line2 hover:text-fg">
          <Icon name="sliders" size={13} />Connections
        </button>
      </div>
    </li>
  );
}

export default function Home() {
  return (
    <div className="mx-auto max-w-[760px] px-8 pt-16">
      <h1 className="text-[24px] font-semibold tracking-tight">Workspaces</h1>
      <p className="mt-1 text-dim">Pick one, or choose what it can read.</p>
      <div className="mt-8"><Ready><ul className="grid grid-cols-2 gap-4"><Card /></ul></Ready></div>
    </div>
  );
}
