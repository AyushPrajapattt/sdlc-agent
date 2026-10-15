"use client";
import { useData } from "@/lib/data";
import Empty from "./Empty";
import { useManage } from "./Shell";

export default function WorkspaceEmpty() {
  const { repos, info, warn } = useData();
  const manage = useManage();
  if (!info) return null;
  return repos.length ? (
    <Empty icon="repo" title="Select a repository">{warn && <p className="text-warn">{warn}</p>}</Empty>
  ) : (
    <Empty icon="repo" title="No repositories connected">
      <p className="mb-3 text-dim">Connect a repository and sync, or load the demo data.</p>
      <button onClick={() => manage(info.workspace.slug)} className="h-8 rounded-md bg-fg px-4 text-[12.5px] font-medium text-bg hover:opacity-90">Connect</button>
    </Empty>
  );
}
