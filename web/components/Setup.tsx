"use client";
// /w/[ws]/setup: a step rail on the left, ONE focused step on the right (sources, AI model, ingest, ask).
// The page itself never scrolls: long content (pickers, stream table) scrolls inside its own box.
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useEffect, useState } from "react";
import { wsApi } from "@/lib/api";
import { repoSlug, useData } from "@/lib/data";
import { fileHref } from "@/lib/workspace";
import { Icon } from "./icons";
import { LlmCard, Sources } from "./Integrations";
import SyncPanel from "./SyncPanel";
import { Chip, Notice, Spinner, btnGhost, btnPrimary, errText } from "./ui";

type StepState = "done" | "todo" | "blocked" | "running";
const started = new Set<string>(); // module-level: survives StrictMode's double effect and remounts
const DEMO_QUESTIONS = ["Why are gateway retries capped at 3?", "Why is the session TTL 15 minutes?"];
const plural = (n: number, w: string) => `${n} ${w}${n === 1 ? "" : "s"}`;

const STEPS = [
  { title: "Sources", sub: "Connect where your engineering history lives." },
  { title: "AI model", sub: "The model that reads the evidence and writes the answer." },
  { title: "Ingest", sub: "Pull history into the graph. You can watch it happen." },
  { title: "Ask", sub: "Open a file and click a line, or ask in the side panel." },
];

function Dot({ n, state }: { n: number; state: StepState }) {
  const base = "grid h-6 w-6 shrink-0 place-items-center rounded-full border text-[11.5px] font-medium";
  if (state === "done") return <span className={`${base} border-ok bg-ok text-bg`}><Icon name="check" size={12} /></span>;
  if (state === "running") return <span className={`${base} border-accent text-accent`}><Spinner /></span>;
  return <span className={`${base} ${state === "blocked" ? "border-line text-dim/60" : "border-line2 text-mute"}`}>{n}</span>;
}

export default function Setup() {
  const router = useRouter();
  const auto = useSearchParams().get("auto") === "1";
  const { ws, info, status, sync, syncLoaded, startSync, connected } = useData();
  const [autoError, setAutoError] = useState("");
  const [opening, setOpening] = useState("");
  const [openError, setOpenError] = useState("");
  const [active, setActive] = useState<number | null>(null); // null = follow the first unfinished step

  useEffect(() => {
    if (!auto || !ws || status !== "ready" || !syncLoaded || started.has(ws)) return;
    started.add(ws);
    router.replace(`/w/${encodeURIComponent(ws)}/setup`); // a reload must not start another run
    if (sync?.state === "running") return;
    startSync("standard").catch((e) => setAutoError(errText(e)));
  }, [auto, ws, status, syncLoaded, sync, startSync, router]);

  if (!ws || !info) return null;
  const demo = info.workspace.demo;
  const ints = info.integrations;
  const n = { repos: connected.repos.length, jira: connected.jira.length, slack: connected.slack.length };
  const hasTargets = n.repos + n.jira + n.slack > 0;
  const dbDown = !info.neo4j.ok;
  const indexed = info.indexed_repos;
  const running = sync?.state === "running";
  const s1 = hasTargets && (demo || (["github", "jira", "slack"] as const).some((k) => ints[k].configured));
  const s2 = ints.llm.configured;
  const s3 = indexed.length > 0 && !running;
  const ready = s1 && s2 && indexed.length > 0;

  const state: StepState[] = [
    s1 ? "done" : "todo",
    s2 ? "done" : "todo",
    running ? "running" : s3 ? "done" : s1 && !dbDown ? "todo" : "blocked",
    ready ? "todo" : "blocked",
  ];
  const provider = info.providers.find((p) => p.configured);
  const summary = [
    demo ? "Demo data, pre-connected" : hasTargets ? [n.repos && plural(n.repos, "repo"), n.jira && plural(n.jira, "project"), n.slack && plural(n.slack, "channel")].filter(Boolean).join(" · ") : "Nothing connected yet",
    s2 ? (provider ? `${provider.name === "azure" ? "Azure OpenAI" : "Sarvam"} ready` : "Configured") : "Needs an API key",
    running ? `Running · ${sync?.totals.persisted ?? 0} stored` : dbDown ? "Waiting for the database" : s3 ? (sync?.graph ? `${sync.graph.artifacts} artifacts · ${sync.graph.edges} links` : "Data ingested") : "Not started",
    ready ? "Ready to ask" : "Finish the steps before",
  ];
  const firstTodo = [s1, s2, s3, ready].findIndex((d) => !d);
  const act = active ?? (firstTodo === -1 ? 3 : firstTodo);
  const done = [s1, s2, s3, false][act];

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
    <div className="h-full min-h-0 overflow-hidden">
      <div className="mx-auto grid h-full max-w-[1040px] grid-cols-[236px_minmax(0,1fr)] gap-8 px-8 py-8 max-md:grid-cols-[minmax(0,1fr)] max-md:grid-rows-[auto_minmax(0,1fr)] max-md:gap-4 max-md:px-4 max-md:py-4">
        <aside aria-label="Setup steps" className="min-h-0 min-w-0">
          <p className="label">Set up</p>
          <h1 className="mt-1 flex flex-wrap items-center gap-2 text-[22px] font-semibold leading-tight tracking-tight">
            {info.workspace.name}
            {demo && <Chip tone="dim"><Icon name="flask" size={11} />demo</Chip>}
          </h1>
          <ol className="mt-6 space-y-1 max-md:mt-3 max-md:flex max-md:space-y-0 max-md:overflow-x-auto">
            {STEPS.map((s, i) => (
              <li key={s.title} className="relative max-md:shrink-0">
                {i < STEPS.length - 1 && <span aria-hidden className="absolute bottom-[-6px] left-[23px] top-[38px] w-px bg-line max-md:hidden" />}
                <button type="button" onClick={() => setActive(i)} aria-current={act === i ? "step" : undefined}
                  className={`flex w-full items-start gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors ${act === i ? "border-line2 bg-raised" : "border-transparent hover:bg-hover"}`}>
                  <Dot n={i + 1} state={state[i]} />
                  <span className="min-w-0">
                    <span className={`block text-[13.5px] font-medium ${state[i] === "blocked" ? "text-dim" : ""}`}>{s.title}</span>
                    <span className="mt-0.5 block truncate text-[11.5px] text-dim max-md:hidden">{summary[i]}</span>
                  </span>
                </button>
              </li>
            ))}
          </ol>
        </aside>

        <main className="flex min-h-0 min-w-0 flex-col gap-3">
          {dbDown && (
            <div className="shrink-0 rounded-lg border border-warn/40 px-3 py-2">
              <Notice tone="warn">
                The graph database (Neo4j) is not reachable. Start it with <code className="font-mono">docker compose up -d</code>, check the NEO4J_* values in <code className="font-mono">.env</code>, restart the API and reload.
              </Notice>
            </div>
          )}
          <section aria-label={STEPS[act].title} className="flex min-h-0 flex-1 flex-col rounded-xl border border-line bg-panel">
            <header className="flex shrink-0 items-start gap-3 border-b border-line px-6 py-4">
              <div className="min-w-0">
                <h2 className="text-[16px] font-semibold tracking-tight">{STEPS[act].title}</h2>
                <p className="mt-0.5 text-[12.5px] text-dim">{act === 0 && demo ? "The demo workspace is already connected." : STEPS[act].sub}</p>
              </div>
              <span aria-live="polite" className="ml-auto shrink-0">
                <Chip tone={state[act] === "done" ? "ok" : state[act] === "running" ? "run" : state[act] === "blocked" ? "warn" : "dim"}>
                  {state[act] === "running" && <Spinner />}{{ done: "done", todo: "to do", blocked: "blocked", running: "running" }[state[act]]}
                </Chip>
              </span>
            </header>

            <div className="min-h-0 flex-1 overflow-auto px-6 py-5">
              {act === 0 && <Sources />}
              {act === 1 && <LlmCard />}
              {act === 2 && (
                <>
                  <SyncPanel />
                  {autoError && <div className="mt-3"><Notice tone="warn">{autoError}</Notice></div>}
                </>
              )}
              {act === 3 && (
                <div className="space-y-5">
                  {!ready && <Notice tone="dim">Still to do: {[!s1 && "connect and select a source", !s2 && "configure the AI model", indexed.length === 0 && "ingest your data"].filter(Boolean).join(", ")}.</Notice>}
                  <button type="button" onClick={() => open()} disabled={!ready || !!opening} className={btnPrimary}>
                    {opening === "open" ? <Spinner /> : <Icon name="arrow" size={12} />}Open workbench
                  </button>
                  {ready && demo && (
                    <div>
                      <p className="label mb-2">Or start with a question</p>
                      <div className="flex flex-col items-start gap-2">
                        {DEMO_QUESTIONS.map((q) => (
                          <button key={q} type="button" onClick={() => open(q)} disabled={!!opening}
                            className="inline-flex h-8 items-center gap-2 rounded-full border border-line px-3 text-[12.5px] text-mute hover:border-line2 hover:text-fg disabled:opacity-40">
                            {opening === q ? <Spinner /> : <Icon name="help" size={12} />}{q}
                          </button>
                        ))}
                      </div>
                      <p className="mt-3 text-[11.5px] text-dim">Or open <span className="font-mono">src/payments/gateway_client.py</span> and click the <span className="font-mono">MAX_RETRIES = 3</span> line.</p>
                    </div>
                  )}
                  {openError && <Notice tone="warn">{openError}</Notice>}
                  <p className="text-[11.5px] text-dim">Manage everything later from <Link href={`/w/${ws}`} className="text-accent hover:underline">the workbench</Link> under Connections.</p>
                </div>
              )}
            </div>

            <footer className="flex shrink-0 items-center gap-2 border-t border-line px-6 py-3">
              {act > 0 && <button type="button" onClick={() => setActive(act - 1)} className={btnGhost}><Icon name="back" size={12} />Back</button>}
              {act < 3 && !done && <span className="ml-auto text-[11.5px] text-dim">{state[act] === "blocked" ? "Waiting on the previous steps" : "Complete this step to continue"}</span>}
              {act < 3 && (
                <button type="button" onClick={() => setActive(act + 1)} disabled={!done} className={`${btnPrimary} ${done ? "ml-auto" : ""}`}>
                  Continue<Icon name="arrow" size={12} />
                </button>
              )}
            </footer>
          </section>
        </main>
      </div>
    </div>
  );
}
