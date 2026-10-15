"use client";
// /w/[ws]/setup: one page, four steps (sources, AI model, ingest, ask) with live status computed from /workbench and the sync job.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState, type ReactNode } from "react";
import { wsApi } from "@/lib/api";
import { repoSlug, useData } from "@/lib/data";
import { fileHref } from "@/lib/workspace";
import { Icon } from "./icons";
import { LlmCard, Sources } from "./Integrations";
import SyncPanel from "./SyncPanel";
import { Chip, Notice, Spinner, btnPrimary, errText } from "./ui";

type StepState = "done" | "todo" | "blocked" | "running";
const CHIP: Record<StepState, { tone: "ok" | "dim" | "warn" | "run"; label: string }> = {
  done: { tone: "ok", label: "done" }, todo: { tone: "dim", label: "to do" }, blocked: { tone: "warn", label: "blocked" }, running: { tone: "run", label: "running" },
};

function Step({ n, title, state, note, children }: { n: number; title: string; state: StepState; note?: string; children: ReactNode }) {
  return (
    <li className="card p-5" aria-label={`Step ${n}: ${title}`}>
      <div className="mb-4 flex items-center gap-3">
        <span className={`grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[12px] font-medium ${state === "done" ? "border-ok bg-ok text-bg" : "border-line2 text-dim"}`}>
          {state === "done" ? <Icon name="check" size={13} /> : n}
        </span>
        <h2 className="text-[15px] font-semibold">{title}</h2>
        <span aria-live="polite" className="ml-auto"><Chip tone={CHIP[state].tone}>{state === "running" && <Spinner />}{CHIP[state].label}</Chip></span>
      </div>
      {note && <p className="mb-3 text-[12px] text-dim">{note}</p>}
      {children}
    </li>
  );
}

const started = new Set<string>(); // module-level: survives StrictMode's double effect and remounts

const DEMO_QUESTIONS = ["Why are gateway retries capped at 3?", "Why is the session TTL 15 minutes?"];

export default function Setup() {
  const router = useRouter();
  const auto = useSearchParams().get("auto") === "1";
  const { ws, info, status, sync, syncLoaded, startSync, connected } = useData();
  const [autoError, setAutoError] = useState("");
  const [opening, setOpening] = useState("");
  const [openError, setOpenError] = useState("");

  useEffect(() => {
    if (!auto || !ws || status !== "ready" || !syncLoaded || started.has(ws)) return;
    started.add(ws);
    router.replace(`/w/${encodeURIComponent(ws)}/setup`); // a reload must not start another run
    const scroll = () => { setTimeout(() => document.getElementById("progress")?.scrollIntoView({ behavior: "smooth", block: "start" }), 150); };
    if (sync?.state === "running") { scroll(); return; }
    startSync("standard").then(scroll, (e) => setAutoError(errText(e)));
  }, [auto, ws, status, syncLoaded, sync, startSync, router]);

  if (!ws || !info) return null;
  const demo = info.workspace.demo;
  const ints = info.integrations;
  const hasTargets = connected.repos.length + connected.jira.length + connected.slack.length > 0;
  const s1 = hasTargets && (demo || (["github", "jira", "slack"] as const).some((k) => ints[k].configured));
  const s2 = ints.llm.configured;
  const indexed = info.indexed_repos;
  const running = sync?.state === "running";
  const dbDown = !info.neo4j.ok;
  const s3 = running ? "running" : indexed.length ? "done" : s1 && !dbDown ? "todo" : "blocked";
  const ready = s1 && s2 && indexed.length > 0;
  const missing = [!s1 && "connect and select a source", !s2 && "configure the AI model", indexed.length === 0 && "ingest your data"].filter(Boolean).join(", ");

  const open = async (question?: string) => {
    const repo = indexed[0];
    if (!repo) return;
    setOpening(question ?? "open"); setOpenError("");
    const base = `/w/${ws}/${repoSlug(repo)}`;
    try {
      const first = (await wsApi.files(ws, repo)).files[0];
      router.push(first ? `${fileHref(base, first)}${question ? `?q=${encodeURIComponent(question)}` : ""}` : base);
    } catch (e) { setOpenError(errText(e)); setOpening(""); }
  };

  return (
    <div className="h-full overflow-auto">
      <div className="mx-auto max-w-[760px] px-8 py-10">
        <h1 className="flex items-center gap-2 text-[24px] font-semibold tracking-tight">
          Set up {info.workspace.name}
          {demo && <Chip tone="dim"><Icon name="flask" size={11} />demo</Chip>}
        </h1>
        <p className="mt-1 text-dim">Connect your sources, add an AI model, ingest, then ask why.</p>
        {dbDown && (
          <div className="mt-4 rounded-lg border border-warn/40 p-3">
            <Notice tone="warn">
              The graph database (Neo4j) is not reachable, so nothing can be ingested or asked yet. Start it with <code className="font-mono">docker compose up -d</code> and check
              NEO4J_URI, NEO4J_USERNAME and NEO4J_PASSWORD in <code className="font-mono">.env</code>, restart the API, then reload this page.
            </Notice>
          </div>
        )}

        <ol className="mt-8 space-y-4">
          <Step n={1} title="Connect sources" state={s1 ? "done" : "todo"}
            note={demo ? undefined : "Credentials are stored on this machine for this workspace only and are never shown again."}>
            <Sources />
          </Step>
          <Step n={2} title="AI model" state={s2 ? "done" : "todo"}><LlmCard /></Step>
          <Step n={3} title="Ingest" state={s3} note={dbDown ? "Waiting for the graph database." : s1 ? undefined : "Connect and select at least one source first."}>
            <SyncPanel />
            {autoError && <div className="mt-2"><Notice tone="warn">{autoError}</Notice></div>}
          </Step>
          <Step n={4} title="Ask" state={ready ? "todo" : "blocked"} note={ready ? undefined : `Still to do: ${missing}.`}>
            <div className="flex flex-wrap items-center gap-2">
              <button type="button" onClick={() => open()} disabled={!ready || !!opening} className={btnPrimary}>
                {opening === "open" ? <Spinner /> : <Icon name="arrow" size={12} />}Open workbench
              </button>
              {ready && demo && <span className="text-[11.5px] text-dim">or try a question:</span>}
              {ready && demo && DEMO_QUESTIONS.map((q) => (
                <button key={q} type="button" onClick={() => open(q)} disabled={!!opening}
                  className="inline-flex h-8 items-center gap-1.5 rounded-full border border-line px-3 text-[12px] text-mute hover:border-line2 hover:text-fg disabled:opacity-40">
                  {opening === q ? <Spinner /> : <Icon name="help" size={12} />}{q}
                </button>
              ))}
              {ready && demo && <span className="inline-flex h-8 items-center gap-1.5 rounded-full border border-dashed border-line px-3 text-[12px] text-dim">Or click a code line in the workbench</span>}
            </div>
            {openError && <div className="mt-2"><Notice tone="warn">{openError}</Notice></div>}
            <p className="mt-3 text-[11.5px] text-dim">
              Manage these later from <Link href={`/w/${ws}`} className="text-accent hover:underline">the workbench</Link> under Connections.
            </p>
          </Step>
        </ol>
      </div>
    </div>
  );
}
