"use client";
// Credential cards, resource pickers and the AI model card. Used by the setup page and the Connections dialog.
// Secret inputs are write-only: values are sent once and never read back; the API's masked hint is all we show.
import { useCallback, useEffect, useMemo, useState } from "react";
import { wsApi } from "@/lib/api";
import { useData } from "@/lib/data";
import type { IntegrationId, Resource, SecretState, TestResult } from "@/lib/types";
import { Icon, type IconName } from "./icons";
import { Chip, Field, Notice, Spinner, btnGhost, btnPrimary, errText, field } from "./ui";

type Source = Exclude<IntegrationId, "llm">;

interface FieldSpec { key: string; label: string; placeholder: string; kind: "secret" | "plain" | "target"; type?: string }
const SPEC: Record<Source, { title: string; icon: IconName; fields: FieldSpec[]; help: string[]; picker: string }> = {
  github: {
    title: "GitHub", icon: "repo", picker: "Repositories",
    fields: [
      { key: "github_token", label: "Token", placeholder: "github_pat_…", kind: "secret" },
      { key: "owner", label: "Owner", placeholder: "user or organisation", kind: "target" },
    ],
    help: [
      "Create a fine-grained personal access token at GitHub > Settings > Developer settings.",
      "Give it read-only access to the repositories you want: Contents, Pull requests, Issues and Metadata.",
      "Owner is the user or organisation that owns them.",
    ],
  },
  jira: {
    title: "Jira", icon: "issue", picker: "Projects",
    fields: [
      { key: "site", label: "Site URL", placeholder: "https://acme.atlassian.net", kind: "target" },
      { key: "jira_email", label: "Email", placeholder: "you@company.com", kind: "plain" },
      { key: "jira_token", label: "API token", placeholder: "Atlassian API token", kind: "secret" },
    ],
    help: [
      "Jira Cloud only. Create an API token at id.atlassian.com > Security > API tokens.",
      "Use the email of the account that owns the token and your https://<name>.atlassian.net site.",
    ],
  },
  slack: {
    title: "Slack", icon: "discussion", picker: "Channels",
    fields: [
      { key: "slack_token", label: "Bot token", placeholder: "xoxb-…", kind: "secret" },
      { key: "workspace", label: "Workspace", placeholder: "subdomain, e.g. acme", kind: "target" },
    ],
    help: [
      "Create a Slack app and add the bot scopes channels:history, groups:history, channels:read and users:read.",
      "Install it to the workspace and paste the Bot User OAuth token (xoxb-…).",
      "Invite the bot to every channel you want to read: /invite @your-bot.",
    ],
  },
};

const ADD_HINT: Record<Source, string> = { github: "owner/repo", jira: "Project key", slack: "Channel id" };

function savedLine(s: SecretState | undefined) {
  if (!s?.set) return "";
  return s.source === "env" ? "set in the server environment" : `saved ${s.hint ?? "••••"}`;
}

/** Password input that never shows a stored secret; a saved one shows its masked hint and a Replace action. */
function SecretInput({ id, label, state, value, onChange, placeholder }: {
  id: string; label: string; state: SecretState | undefined; value: string; onChange: (v: string) => void; placeholder: string;
}) {
  const [replacing, setReplacing] = useState(false);
  const stored = !!state?.set && !replacing;
  useEffect(() => { setReplacing(false); }, [state?.hint, state?.set]); // a successful save returns to the masked view
  return (
    <div className="flex flex-col gap-1 text-[11.5px] text-dim">
      <label htmlFor={id}>{label}</label>
      <div className="flex items-center gap-2">
      {stored ? (
        <>
          <span id={id} className="flex h-8 min-w-0 flex-1 items-center gap-1.5 truncate rounded-md border border-line px-2 font-mono text-[12px] text-mute">
            <Icon name="lock" size={12} className="text-dim" />{savedLine(state)}
          </span>
          <button type="button" onClick={() => setReplacing(true)} className={btnGhost}>Replace</button>
        </>
      ) : (
        <>
          <input id={id} type="password" autoComplete="new-password" spellCheck={false} value={value} placeholder={placeholder}
            onChange={(e) => onChange(e.target.value)} className={field} />
          {state?.set && <button type="button" onClick={() => { setReplacing(false); onChange(""); }} className={btnGhost}>Cancel</button>}
        </>
      )}
      </div>
    </div>
  );
}

function Help({ lines }: { lines: string[] }) {
  return (
    <details className="text-[11.5px] text-dim">
      <summary className="cursor-pointer select-none hover:text-mute">Where do I get this token?</summary>
      <ul className="mt-1.5 list-disc space-y-0.5 pl-4">{lines.map((l) => <li key={l}>{l}</li>)}</ul>
    </details>
  );
}

function TestLine({ result, error }: { result: TestResult | null; error: string }) {
  if (error) return <Notice tone="warn">{error}</Notice>;
  if (!result) return null;
  return <Notice tone={result.ok ? "ok" : "warn"}>{result.ok ? "Connected" : "Failed"}{result.account ? ` as ${result.account}` : ""}: {result.detail}</Notice>;
}

// ---------- picker ----------

function Picker({ kind, reloadKey }: { kind: Source; reloadKey: number }) {
  const { ws, info, connected, targets, saveTargets } = useData();
  const spec = SPEC[kind];
  const [res, setRes] = useState<{ items: Resource[]; error: string; loading: boolean }>({ items: [], error: "", loading: true });
  const [draft, setDraft] = useState<string[] | null>(null);
  const [q, setQ] = useState("");
  const [adding, setAdding] = useState("");
  const [err, setErr] = useState("");
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [again, setAgain] = useState(0);
  const owner = targets?.github.owner ?? "";

  useEffect(() => {
    if (!ws) return;
    let live = true;
    wsApi.resources(ws, kind).then(
      (r) => live && setRes({ items: r.resources, error: "", loading: false }),
      (e) => live && setRes({ items: [], error: errText(e), loading: false }),
    );
    return () => { live = false; };
  }, [ws, kind, reloadKey, again]);

  const base = kind === "github" ? connected.repos : kind === "jira" ? connected.jira : connected.slack;
  const sel = draft ?? base;
  const full = useCallback((id: string) => (kind === "github" && !id.includes("/") && owner ? `${owner}/${id}` : id), [kind, owner]);
  const rows = useMemo(() => {
    const m = new Map<string, Resource>();
    for (const r of res.items) m.set(full(r.id), { ...r, id: full(r.id) });
    for (const id of sel) if (!m.has(id)) m.set(id, { id, name: id });
    const s = q.trim().toLowerCase();
    return [...m.values()].filter((r) => !s || r.id.toLowerCase().includes(s) || r.name.toLowerCase().includes(s));
  }, [res.items, sel, q, full]);
  if (!info) return null;
  const dirty = draft !== null && (draft.length !== base.length || draft.some((x) => !base.includes(x)));

  const toggle = (id: string) => { setErr(""); setDone(false); setDraft(sel.includes(id) ? sel.filter((x) => x !== id) : [...sel, id]); };
  const add = () => {
    const v = adding.trim();
    if (!v) return;
    const id = kind === "jira" ? v.toUpperCase() : full(v);
    if (kind === "github" && !/^[\w.-]+\/[\w.-]+$/.test(id)) return setErr("Use the form owner/repo (or set the Owner above and enter just the repo name).");
    setErr(""); setDone(false); setAdding("");
    if (!sel.includes(id)) setDraft([...sel, id]);
  };
  const save = async () => {
    setBusy(true); setErr(""); setDone(false);
    try {
      if (kind === "github") {
        const owners = [...new Set(sel.map((r) => r.split("/")[0]))];
        if (owners.length > 1) throw new Error(`All repositories must share one owner (${owners[0]}).`);
        const o = owners[0] || owner;
        await saveTargets({ github: { owner: o, repos: sel.map((r) => (r.startsWith(`${o}/`) ? r.slice(o.length + 1) : r)) } });
      } else if (kind === "jira") {
        await saveTargets({ jira: { projects: sel } });
      } else {
        await saveTargets({ slack: { channels: sel } });
      }
      setDraft(null); setDone(true);
    } catch (e) { setErr(errText(e)); } finally { setBusy(false); }
  };

  const label = (r: Resource) => (kind === "slack" && r.name !== r.id ? `#${r.name.replace(/^#/, "")}` : kind === "jira" && r.name !== r.id ? r.id : r.id);
  const sub = (r: Resource) => (kind === "slack" ? (r.name !== r.id ? r.id : "") : kind === "jira" ? (r.name !== r.id ? r.name : "") : r.detail ?? "");

  return (
    <section aria-label={spec.picker} className="rounded-lg border border-line bg-bg p-3">
      <div className="mb-2 flex items-center gap-2">
        <h4 className="label">{spec.picker}</h4>
        <span className="text-[11.5px] text-dim">{sel.length} selected</span>
        <button type="button" onClick={() => { setRes((r) => ({ ...r, loading: true, error: "" })); setAgain((n) => n + 1); }} className="ml-auto text-[11.5px] text-dim hover:text-fg">Reload</button>
      </div>
      {res.loading && <p className="flex items-center gap-2 py-2 text-dim"><Spinner />Loading {spec.picker.toLowerCase()}…</p>}
      {res.error && <Notice tone="warn">{res.error}</Notice>}
      {!res.loading && (
        <>
          <div className="relative mb-1.5">
            <Icon name="search" size={12} className="pointer-events-none absolute left-2 top-2.5 text-dim" />
            <input value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search…" aria-label={`Search ${spec.picker.toLowerCase()}`} className={`${field} w-full pl-7`} />
          </div>
          <ul className="max-h-[250px] overflow-auto rounded-md border border-line bg-bg">
            {rows.length === 0 && <li className="px-3 py-3 text-center text-dim">{res.items.length ? "No matches" : "Nothing found. Add one by id below."}</li>}
            {rows.map((r) => (
              <li key={r.id}>
                <label className="flex min-h-8 cursor-pointer items-center gap-2 px-2.5 py-1 hover:bg-panel">
                  <input type="checkbox" checked={sel.includes(r.id)} onChange={() => toggle(r.id)} className="h-3.5 w-3.5 accent-[var(--accent)]" />
                  <span className="truncate font-mono text-[12.5px]">{label(r)}</span>
                  {sub(r) && <span className="truncate text-[11.5px] text-dim">{sub(r)}</span>}
                  {r.private && <span className="ml-auto flex shrink-0 items-center gap-1 text-[11px] text-dim"><Icon name="lock" size={11} />private</span>}
                </label>
              </li>
            ))}
          </ul>
        </>
      )}
      <form onSubmit={(e) => { e.preventDefault(); add(); }} className="mt-2 flex gap-2">
        <input value={adding} onChange={(e) => setAdding(e.target.value)} placeholder={`Add by id: ${ADD_HINT[kind]}`} aria-label={`Add ${spec.picker.toLowerCase()} by id`} className={field} />
        <button type="submit" aria-label="Add" className="grid h-8 w-8 place-items-center rounded-md border border-line text-mute hover:border-line2 hover:text-fg"><Icon name="plus" size={13} /></button>
      </form>
      <div className="mt-2 flex items-center gap-2">
        <button type="button" onClick={save} disabled={busy || !dirty} className={btnPrimary}>{busy && <Spinner />}Save selection</button>
        {done && <Notice tone="ok">Selection saved</Notice>}
        {err && <Notice tone="warn">{err}</Notice>}
      </div>
    </section>
  );
}

// ---------- integration card ----------

function IntegrationCard({ kind }: { kind: Source }) {
  const { ws, info, targets, refresh, saveTargets } = useData();
  const spec = SPEC[kind];
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [error, setError] = useState("");
  const [reload, setReload] = useState(0);
  if (!ws || !info || !targets) return null;
  const status = info.integrations[kind];
  const target = (key: string) => (key === "owner" ? targets.github.owner : key === "site" ? targets.jira.site : targets.slack.workspace);
  const val = (f: FieldSpec) => draft[f.key] ?? (f.kind === "target" ? target(f.key) : f.kind === "plain" ? status.secrets[f.key]?.value ?? "" : "");

  const saveAndTest = async () => {
    setBusy(true); setError(""); setResult(null);
    try {
      const secrets: Record<string, string> = {};
      for (const f of spec.fields) {
        const v = draft[f.key]?.trim();
        if (f.kind === "secret" && v) secrets[f.key] = v;
        if (f.kind === "plain" && v !== undefined && v !== (status.secrets[f.key]?.value ?? "")) secrets[f.key] = v;
      }
      if (Object.keys(secrets).length) await wsApi.saveSecrets(ws, secrets);
      const o = draft.owner?.trim(), site = draft.site?.trim(), sw = draft.workspace?.trim();
      if (o !== undefined && o !== targets.github.owner) await saveTargets({ github: { owner: o } });
      if (site !== undefined && site !== targets.jira.site) await saveTargets({ jira: { site } });
      if (sw !== undefined && sw !== targets.slack.workspace) await saveTargets({ slack: { workspace: sw } });
      setDraft({});
      setResult(await wsApi.test(ws, kind));
      await refresh();
      setReload((n) => n + 1);
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  };

  const credsReady = spec.fields.filter((f) => f.kind !== "target").every((f) => status.secrets[f.key]?.set);
  return (
    <div className="@container">
      <div className="grid gap-5 @xl:grid-cols-[minmax(0,300px)_minmax(0,1fr)]">
    <div className="space-y-3">
      <div className="flex items-center gap-2">
        <h3 className="label">Credentials</h3>
        {status.configured ? <Chip tone="ok"><Icon name="check" size={11} />connected</Chip> : <Chip tone="dim">not connected</Chip>}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); saveAndTest(); }} className="space-y-3">
        {spec.fields.map((f) => {
          const id = `${ws}-${f.key}`;
          return f.kind === "secret" ? (
            <SecretInput key={f.key} id={id} label={f.label} state={status.secrets[f.key]} value={draft[f.key] ?? ""} placeholder={f.placeholder}
              onChange={(v) => setDraft((d) => ({ ...d, [f.key]: v }))} />
          ) : (
            <Field key={f.key} label={f.label}>
              <input value={val(f)} placeholder={f.placeholder} spellCheck={false} onChange={(e) => setDraft((d) => ({ ...d, [f.key]: e.target.value }))} className={field} />
            </Field>
          );
        })}
        <div className="flex items-center gap-2 pt-1">
          <button type="submit" disabled={busy} className={btnPrimary}>{busy && <Spinner />}Save &amp; test</button>
          <span aria-live="polite" className="min-w-0"><TestLine result={result} error={error} /></span>
        </div>
      </form>
      <Help lines={spec.help} />
    </div>
    <div>
      {/* `configured` also needs a selection, so the picker opens as soon as the credentials are stored */}
      {credsReady ? <Picker kind={kind} reloadKey={reload} /> : (
        <div className="grid h-full min-h-[140px] place-items-center rounded-lg border border-dashed border-line px-4 text-center text-[12px] text-dim">
          Save and test your credentials, then choose which {spec.picker.toLowerCase()} to ingest.
        </div>
      )}
    </div>
      </div>
    </div>
  );
}

const SOURCES: Source[] = ["github", "jira", "slack"];

/** Step 1: one tab per source (credentials | picker). Demo workspaces show only the demo catalog pickers. */
export function Sources() {
  const { info } = useData();
  const [tab, setTab] = useState<Source>("github");
  if (!info) return null;
  const demo = info.workspace.demo;
  return (
    <div>
      <div role="tablist" aria-label="Sources" className="mb-4 flex gap-1 border-b border-line">
        {SOURCES.map((k) => {
          const on = tab === k;
          const ok = demo || info.integrations[k].configured;
          return (
            <button key={k} type="button" role="tab" aria-selected={on} onClick={() => setTab(k)}
              className={`-mb-px flex h-9 items-center gap-2 border-b-2 px-3 text-[13px] ${on ? "border-accent text-fg" : "border-transparent text-dim hover:text-mute"}`}>
              <Icon name={SPEC[k].icon} size={13} />{SPEC[k].title}
              <i aria-label={ok ? "connected" : "not connected"} className={`h-1.5 w-1.5 rounded-full ${ok ? "bg-ok" : "bg-line2"}`} />
            </button>
          );
        })}
      </div>
      <div role="tabpanel" aria-label={SPEC[tab].title}>
        {demo ? (
          <div className="space-y-3">
            <p className="flex items-center gap-2 text-ok"><Icon name="flask" size={14} />Demo data: no credentials needed</p>
            <Picker key={tab} kind={tab} reloadKey={0} />
          </div>
        ) : <IntegrationCard key={tab} kind={tab} />}
      </div>
    </div>
  );
}

// ---------- AI model ----------

export function LlmCard() {
  const { ws, info, refresh } = useData();
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [result, setResult] = useState<TestResult | null>(null);
  const [error, setError] = useState("");
  if (!ws || !info) return null;
  const st = info.integrations.llm;
  const sec = st.secrets;
  const provider = draft.llm_provider ?? sec.llm_provider?.value ?? "azure";
  const plain = (k: string) => draft[k] ?? sec[k]?.value ?? "";
  const keyName = provider === "azure" ? "azure_key" : "sarvam_key";

  const saveAndTest = async () => {
    setBusy(true); setError(""); setResult(null);
    try {
      const body: Record<string, string> = { llm_provider: provider };
      for (const k of ["llm_model", "azure_endpoint"]) if (draft[k] !== undefined) body[k] = draft[k].trim();
      if (draft[keyName]?.trim()) body[keyName] = draft[keyName].trim();
      await wsApi.saveSecrets(ws, body);
      setDraft({});
      setResult(await wsApi.test(ws, "llm"));
      await refresh();
    } catch (e) { setError(errText(e)); } finally { setBusy(false); }
  };

  return (
    <div className="max-w-[420px] space-y-3">
      <div className="flex items-center gap-2">
        {st.configured ? <Chip tone="ok"><Icon name="check" size={11} />configured</Chip> : <Chip tone="dim">not configured</Chip>}
      </div>
      <form onSubmit={(e) => { e.preventDefault(); saveAndTest(); }} className="space-y-3">
        <Field label="Provider">
          <select value={provider} onChange={(e) => setDraft((d) => ({ ...d, llm_provider: e.target.value }))} className={`${field} font-sans`}>
            <option value="azure">Azure OpenAI</option>
            <option value="sarvam">Sarvam</option>
          </select>
        </Field>
        {provider === "azure" && (
          <Field label="Endpoint">
            <input value={plain("azure_endpoint")} placeholder="https://<resource>.openai.azure.com" spellCheck={false}
              onChange={(e) => setDraft((d) => ({ ...d, azure_endpoint: e.target.value }))} className={field} />
          </Field>
        )}
        <SecretInput key={keyName} id={`${ws}-${keyName}`} label="API key" state={sec[keyName]} value={draft[keyName] ?? ""} placeholder="API key"
          onChange={(v) => setDraft((d) => ({ ...d, [keyName]: v }))} />
        <Field label="Model (optional)">
          <input value={plain("llm_model")} placeholder={provider === "azure" ? "deployment name" : "default"} spellCheck={false}
            onChange={(e) => setDraft((d) => ({ ...d, llm_model: e.target.value }))} className={field} />
        </Field>
        <div className="flex items-center gap-2 pt-1">
          <button type="submit" disabled={busy} className={btnPrimary}>{busy && <Spinner />}Save &amp; test</button>
          <span aria-live="polite" className="min-w-0"><TestLine result={result} error={error} /></span>
        </div>
      </form>
    </div>
  );
}
