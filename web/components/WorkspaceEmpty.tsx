"use client";
// /w/[ws]: go straight to the first indexed repo, or to the setup checklist when nothing is ingested yet.
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { repoSlug, useData } from "@/lib/data";
import Empty from "./Empty";

export default function WorkspaceEmpty() {
  const router = useRouter();
  const { ws, info, status, warn } = useData();
  const first = info?.indexed_repos[0];
  useEffect(() => {
    if (status === "ready" && ws) router.replace(first ? `/w/${ws}/${repoSlug(first)}` : `/w/${ws}/setup`);
  }, [status, ws, first, router]);
  return <Empty icon="repo" title="Opening…">{warn && <p className="text-warn">{warn}</p>}</Empty>;
}
