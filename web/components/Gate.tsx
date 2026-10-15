"use client";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { api } from "@/lib/api";
import { WS, useData } from "@/lib/data";
import type { Investigation } from "@/lib/types";
import Empty from "./Empty";
import RepoShell from "./RepoShell";
import Workbench from "./Workbench";

const btn = "h-8 rounded-md bg-fg px-4 text-[12.5px] font-medium text-bg hover:opacity-90";

/** Renders children once /api/workbench has loaded; otherwise a loading or backend-down state. */
export function Ready({ children }: { children: ReactNode }) {
  const { status, error, refresh } = useData();
  if (status === "loading") return <Empty icon="spark" title="Loading…" />;
  if (status === "error") return (
    <Empty icon="alert" title="Backend unavailable">
      <p className="mb-3 max-w-[360px] text-dim">{error}</p>
      <button onClick={refresh} className={btn}>Retry</button>
    </Empty>
  );
  return <>{children}</>;
}

export function Unknown({ what }: { what: string }) {
  return <Empty icon="alert" title={`Unknown ${what}`}><Link href="/" className="text-accent hover:underline">All workspaces</Link></Empty>;
}

export const isWs = (ws: string | undefined) => ws === WS;

function Repo({ slug, children }: { slug: string; children: (repoName: string) => ReactNode }) {
  const { repoByslug } = useData();
  const name = repoByslug(slug);
  return name ? <>{children(name)}</> : <Unknown what="repository" />;
}

export function RepoPage({ repo }: { repo: string }) {
  const { isIndexed } = useData();
  return (
    <Ready>
      <Repo slug={repo}>{(name) => <RepoShell base={`/w/${WS}/${repo}`} icon="file" title={isIndexed(name) ? "Select a file" : "Not synced yet"} />}</Repo>
    </Ready>
  );
}

export function FilePage({ repo, path }: { repo: string; path: string }) {
  return (
    <Ready>
      <Repo slug={repo}>{(name) => <Workbench key={path} ws={WS} repo={repo} repoName={name} file={path} inv={null} />}</Repo>
    </Ready>
  );
}

/** A stored investigation: from the in-session cache when it was just streamed, else GET /api/investigations/{id}. */
export function WhyPage({ repo, id }: { repo: string; id: string }) {
  const { recall, absorb, remember } = useData();
  const [st, set] = useState<{ id: string; inv: Investigation | null; error: string }>({ id: "", inv: null, error: "" });
  const cached = recall(id);
  useEffect(() => {
    if (cached) return;
    api<{ investigation: Investigation; graph: Parameters<typeof absorb>[0] }>(`/api/investigations/${encodeURIComponent(id)}`).then(
      (r) => { absorb(r.graph); remember(r.investigation); set({ id, inv: r.investigation, error: "" }); },
      (e: Error) => set({ id, inv: null, error: (e as { status?: number }).status === 404 ? "not-found" : e.message }),
    );
  }, [id, cached, absorb, remember]);
  const inv = cached ?? (st.id === id ? st.inv : null);
  return (
    <Ready>
      <Repo slug={repo}>
        {(name) => inv ? <Workbench key={id} ws={WS} repo={repo} repoName={name} file={inv.file ?? null} inv={inv} />
          : st.id === id && st.error === "not-found" ? <Unknown what="investigation" />
          : st.id === id && st.error ? <Empty icon="alert" title="Could not load the investigation"><p className="text-dim">{st.error}</p></Empty>
          : <Empty icon="spark" title="Loading…" />}
      </Repo>
    </Ready>
  );
}
