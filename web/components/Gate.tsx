"use client";
import Link from "next/link";
import { useEffect, useState, type ReactNode } from "react";
import { wsApi } from "@/lib/api";
import { useData } from "@/lib/data";
import type { Investigation } from "@/lib/types";
import Empty from "./Empty";
import RepoShell from "./RepoShell";
import { btnPrimary } from "./ui";
import Workbench from "./Workbench";

/** Renders children once the workspace's /workbench has loaded; otherwise a loading, unknown-workspace or backend-down state. */
export function Ready({ children }: { children: ReactNode }) {
  const { status, error, refresh } = useData();
  if (status === "loading" || status === "idle") return <Empty icon="spark" title="Loading…" />;
  if (status === "notfound") return <Unknown what="workspace" />;
  if (status === "error") return (
    <Empty icon="alert" title="Backend unavailable">
      <p className="mb-3 max-w-[360px] text-dim">{error}</p>
      <button onClick={refresh} className={btnPrimary}>Retry</button>
    </Empty>
  );
  return <>{children}</>;
}

export function Unknown({ what }: { what: string }) {
  return <Empty icon="alert" title={`Unknown ${what}`}><Link href="/" className="text-accent hover:underline">All workspaces</Link></Empty>;
}

/** Empty state that sends the user to the onboarding checklist. */
export function SetupCta({ ws, icon = "repo", title, text }: { ws: string; icon?: "repo" | "file"; title: string; text: string }) {
  return (
    <Empty icon={icon} title={title}>
      <p className="mb-3 max-w-[360px] text-dim">{text}</p>
      <Link href={`/w/${ws}/setup`} className={btnPrimary}>Set up this workspace</Link>
    </Empty>
  );
}

function Repo({ ws, slug, children }: { ws: string; slug: string; children: (repoName: string) => ReactNode }) {
  const { repoByslug, repos } = useData();
  const name = repoByslug(slug);
  if (name) return <>{children(name)}</>;
  return repos.length === 0
    ? <SetupCta ws={ws} title="No repositories connected" text="Connect a source and ingest it to explore its history." />
    : <Unknown what="repository" />;
}

export function RepoPage({ ws, repo }: { ws: string; repo: string }) {
  const { isIndexed } = useData();
  return (
    <Ready>
      <Repo ws={ws} slug={repo}>
        {(name) => isIndexed(name)
          ? <RepoShell base={`/w/${ws}/${repo}`} icon="file" title="Select a file" />
          : <SetupCta ws={ws} title="Not synced yet" text="This repository has no ingested history yet. Run the ingestion from the setup page." />}
      </Repo>
    </Ready>
  );
}

export function FilePage({ ws, repo, path }: { ws: string; repo: string; path: string }) {
  return (
    <Ready>
      <Repo ws={ws} slug={repo}>{(name) => <Workbench key={path} ws={ws} repo={repo} repoName={name} file={path} inv={null} />}</Repo>
    </Ready>
  );
}

/** A stored investigation: from the in-session cache when it was just streamed, else GET /api/w/{ws}/investigations/{id}. */
export function WhyPage({ ws, repo, id }: { ws: string; repo: string; id: string }) {
  const { recall, absorb, remember } = useData();
  const [st, set] = useState<{ id: string; inv: Investigation | null; error: string }>({ id: "", inv: null, error: "" });
  const cached = recall(id);
  useEffect(() => {
    if (cached) return;
    wsApi.investigation(ws, id).then(
      (r) => { absorb(r.graph); remember(r.investigation); set({ id, inv: r.investigation, error: "" }); },
      (e: Error) => set({ id, inv: null, error: (e as { status?: number }).status === 404 ? "not-found" : e.message }),
    );
  }, [ws, id, cached, absorb, remember]);
  const inv = cached ?? (st.id === id ? st.inv : null);
  return (
    <Ready>
      <Repo ws={ws} slug={repo}>
        {(name) => inv ? <Workbench key={id} ws={ws} repo={repo} repoName={name} file={inv.file ?? null} inv={inv} />
          : st.id === id && st.error === "not-found" ? <Unknown what="investigation" />
          : st.id === id && st.error ? <Empty icon="alert" title="Could not load the investigation"><p className="text-dim">{st.error}</p></Empty>
          : <Empty icon="spark" title="Loading…" />}
      </Repo>
    </Ready>
  );
}
