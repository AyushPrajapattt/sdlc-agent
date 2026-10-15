"use client";
import { useConfig } from "@/lib/config";
import Empty from "./Empty";
import { useManage } from "./Shell";

export default function WorkspaceEmpty({ ws }: { ws: string }) {
  const [cfg] = useConfig(ws);
  const manage = useManage();
  return cfg.repos.length ? <Empty icon="repo" title="Select a repository" /> : (
    <Empty icon="repo" title="No repositories connected">
      <button onClick={() => manage(ws)} className="h-8 rounded-md bg-fg px-4 text-[12.5px] font-medium text-bg hover:opacity-90">Connect</button>
    </Empty>
  );
}
