"use client";
import Link from "next/link";
import { Fragment, useState } from "react";
import { useConfig } from "@/lib/config";
import { INDEXED_REPO, repoByslug, repoSlug } from "@/lib/workspaces";
import { buildTree, hasPreview, type TreeNode } from "@/lib/workspace";
import { Icon } from "./icons";
import { useLocation, useManage } from "./Shell";

const TREE = buildTree();

function Tree({ nodes, base, active, depth = 0 }: { nodes: TreeNode[]; base: string; active?: string; depth?: number }) {
  const [closed, setClosed] = useState<string[]>([]);
  return (
    <>
      {nodes.map((n) =>
        n.dir ? (
          <Fragment key={n.path}>
            <button onClick={() => setClosed((c) => (c.includes(n.path) ? c.filter((x) => x !== n.path) : [...c, n.path]))}
              style={{ paddingLeft: 8 + depth * 14 }}
              className="flex h-7 w-full items-center gap-1.5 rounded-md pr-2 text-left text-mute hover:bg-hover hover:text-fg">
              <Icon name="chevron" size={11} className={`text-dim transition-transform ${closed.includes(n.path) ? "-rotate-90" : ""}`} />
              <span className="truncate font-mono text-[12px]">{n.name}</span>
            </button>
            {!closed.includes(n.path) && <Tree nodes={n.children} base={base} active={active} depth={depth + 1} />}
          </Fragment>
        ) : (
          <Link key={n.path} href={`${base}/f/${n.path}`} style={{ paddingLeft: 8 + depth * 14 + 15 }} aria-current={active === n.path ? "page" : undefined}
            className={`flex h-7 items-center gap-2 rounded-md pr-2 ${active === n.path ? "bg-raised text-fg" : "text-mute hover:bg-hover hover:text-fg"}`}>
            <span className="truncate font-mono text-[12px]">{n.name}</span>
            {hasPreview(n.path) && <i className="ml-auto h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />}
          </Link>
        ),
      )}
    </>
  );
}

export default function LeftPane({ ws }: { ws: string }) {
  const { repo: slug, file } = useLocation();
  const [cfg] = useConfig(ws);
  const manage = useManage();
  const repo = slug ? repoByslug(slug) : undefined;

  return (
    <aside className="flex h-full w-[240px] shrink-0 flex-col border-r border-line bg-panel" aria-label="Repositories">
      {repo ? (
        <>
          <Link href={`/w/${ws}`} className="flex h-10 shrink-0 items-center gap-1.5 border-b border-line px-3 text-[12px] text-dim hover:text-fg">
            <Icon name="back" size={13} />All repositories
          </Link>
          <div className="flex h-10 shrink-0 items-center gap-2 px-3">
            <Icon name="repo" size={14} className="text-dim" />
            <Link href={`/w/${ws}/${slug}`} className="truncate font-medium hover:underline">{repo}</Link>
          </div>
          <nav className="min-h-0 flex-1 overflow-auto px-2 pb-3">
            {!cfg.repos.includes(repo) ? (
              <p className="px-2 py-3 text-dim">Not connected.</p>
            ) : repo !== INDEXED_REPO ? (
              <p className="px-2 py-3 text-dim">Indexing…</p>
            ) : (
              <Tree nodes={TREE} base={`/w/${ws}/${slug}`} active={file} />
            )}
          </nav>
        </>
      ) : (
        <>
          <div className="flex h-10 shrink-0 items-center px-3"><span className="label">Repositories</span></div>
          <nav className="min-h-0 flex-1 overflow-auto px-2">
            {cfg.repos.map((r) => (
              <Link key={r} href={`/w/${ws}/${repoSlug(r)}`} className="flex h-8 items-center gap-2 rounded-md px-2 text-mute hover:bg-hover hover:text-fg">
                <Icon name="repo" size={14} className="text-dim" /><span className="truncate">{r}</span>
                {r !== INDEXED_REPO && <span className="ml-auto text-[11px] text-warn">indexing</span>}
              </Link>
            ))}
            {cfg.repos.length === 0 && <p className="px-2 py-3 text-dim">No repositories yet.</p>}
          </nav>
          <div className="border-t border-line p-2">
            <button onClick={() => manage(ws)} className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-mute hover:bg-hover hover:text-fg">
              <Icon name="plus" size={13} />Connect
            </button>
          </div>
        </>
      )}
    </aside>
  );
}
