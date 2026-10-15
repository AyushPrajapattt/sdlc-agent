"use strict";
// All API text goes through textContent / setAttribute on vetted values; never innerHTML.
const $ = (id) => document.getElementById(id);
const SVGNS = "http://www.w3.org/2000/svg";

function el(tag, attrs, ...kids) {
  const n = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  for (const k of kids) n.append(k);
  return n;
}
function svg(tag, attrs, text) {
  const n = document.createElementNS(SVGNS, tag);
  for (const [k, v] of Object.entries(attrs || {})) n.setAttribute(k, v);
  if (text !== undefined) n.textContent = text;
  return n;
}
const safeUrl = (u) => (typeof u === "string" && /^https?:\/\//i.test(u) ? u : null);
const list = (s) => s.split(",").map((x) => x.trim()).filter(Boolean);
const clip = (s, n) => { s = String(s ?? ""); return s.length > n ? s.slice(0, n - 1) + "…" : s; };

async function api(path, opts) {
  const r = await fetch(path, opts);
  let body = null;
  try { body = await r.json(); } catch (_) { /* non-JSON error */ }
  if (!r.ok) throw new Error((body && typeof body.detail === "string" && body.detail) || `Request failed (${r.status})`);
  return body;
}

/* ---------- workspace / status ---------- */
const SOURCES = [["github", "GitHub"], ["jira", "Jira"], ["slack", "Slack"]];

async function loadStatus() {
  let s;
  try { s = await api("/api/status"); } catch (e) { $("neo4j").className = "pill bad"; $("neo4j").textContent = "API unreachable"; return; }
  const n = $("neo4j");
  n.className = "pill " + (s.neo4j.ok ? "ok" : "bad");
  n.textContent = s.neo4j.ok ? `Neo4j ok - ${s.neo4j.counts.artifacts} artifacts, ${s.neo4j.counts.edges} edges` : "Neo4j: " + s.neo4j.error;
  const box = $("sources");
  box.replaceChildren();
  const byProv = (s.neo4j.ok && s.neo4j.counts.by_provider) || {};
  for (const [key, label] of SOURCES) {
    const src = s.sources[key];
    box.append(el("div", { class: "card" },
      el("b", {}, label),
      el("span", { class: src.configured ? "ok" : "bad" }, src.configured ? "configured" : "not configured"),
      document.createTextNode(" / "),
      el("span", { class: src.token_present ? "ok" : "bad" }, src.token_present ? "token present" : "token missing"),
      el("span", {}, ` / ${byProv[key] ?? 0} artifacts`)));
  }
  const sel = $("provider"), prev = sel.value;
  sel.replaceChildren(el("option", { value: "" }, "default"));
  for (const p of s.providers) {
    const o = el("option", { value: p.name }, `${p.name} (${p.model})${p.configured ? "" : " - not configured"}`);
    if (!p.configured) o.disabled = true;
    sel.append(o);
  }
  sel.value = [...sel.options].some((o) => o.value === prev && !o.disabled) ? prev : "";
}

const F = () => $("wsform").elements;
async function loadWorkspace() {
  try {
    const w = await api("/api/workspace"), f = F();
    f.gh_owner.value = w.github.owner; f.gh_repos.value = w.github.repos.join(", ");
    f.jira_site.value = w.jira.site; f.jira_projects.value = w.jira.projects.join(", ");
    f.slack_ws.value = w.slack.workspace; f.slack_channels.value = w.slack.channels.join(", ");
  } catch (e) { setMsg("wsmsg", e.message, true); }
}
function setMsg(id, text, bad) { const m = $(id); m.textContent = text; m.className = "msg" + (bad ? " bad" : ""); }

$("wsform").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const f = F();
  let site = f.jira_site.value.trim();
  if (site && !/^https?:\/\//i.test(site)) site = "https://" + site;
  const body = {
    github: { owner: f.gh_owner.value, repos: list(f.gh_repos.value) },
    jira: { site, projects: list(f.jira_projects.value) },
    slack: { workspace: f.slack_ws.value, channels: list(f.slack_channels.value) },
  };
  try {
    await api("/api/workspace", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    setMsg("wsmsg", "Saved.");
    await loadWorkspace(); loadStatus();
  } catch (e) { setMsg("wsmsg", e.message, true); }
});

function showRuns(summaries) {
  const box = $("runs");
  box.replaceChildren();
  for (const s of summaries || []) {
    const row = el("div", { class: "run" });
    for (const [k, v] of Object.entries(s)) {
      const val = typeof v === "object" && v !== null ? JSON.stringify(v) : String(v);
      row.append(el("div", {}, `${k}: ${clip(val, 300)}`));
    }
    box.append(row);
  }
}
async function runSync(path, body, btn) {
  const btns = [$("syncbtn"), $("demobtn")];
  btns.forEach((b) => (b.disabled = true));
  setMsg("syncmsg", "Running... this can take a while.");
  $("runs").replaceChildren();
  try {
    const r = await api(path, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
    showRuns(r.summaries);
    setMsg("syncmsg", r.complete === false ? "Finished with INCOMPLETE streams: the graph may be partial (see run summaries)." : "Finished.");
  } catch (e) { setMsg("syncmsg", "Failed: " + e.message, true); }
  btns.forEach((b) => (b.disabled = false));
  loadStatus();
}
$("syncbtn").addEventListener("click", () => runSync("/api/sync", { demo: false }));
$("demobtn").addEventListener("click", () => runSync("/api/demo", {}));

/* ---------- modes ---------- */
const TRACE = "Traceback (most recent call last):\n  File \"src/auth/session_cache.py\", line 58, in get\n    return self._store[key]\nKeyError: 'sess-42'\n\nWhy does this session expire so quickly?";
const MODES = {
  why: { ph: "Ask why code, config or a decision is the way it is...", ex: ["Why are gateway retries capped at 3?", "Why is the session TTL 15 minutes?", "Why did we choose Redis for the session cache?"] },
  debug: { ph: "Paste an error message or stack trace...", ex: [TRACE, "KeyError in src/auth/session_cache.py get() right after login", "Gateway returns 502 after exactly 3 retries"] },
  change: { ph: "Describe a change and ask if it is safe...", ex: ["Can I raise MAX_RETRIES in src/payments/gateway_client.py?", "Is it safe to change the session TTL in src/auth/session_cache.py?", "Can I remove the retry cap of 3?"] },
};
let mode = "why";
function setMode(m) {
  mode = m;
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.mode === m)));
  $("q").placeholder = MODES[m].ph;
  const chips = $("chips");
  chips.replaceChildren();
  for (const ex of MODES[m].ex) {
    const b = el("button", { type: "button", title: ex }, clip(ex.split("\n")[0], 60));
    b.addEventListener("click", () => { $("q").value = ex; $("q").focus(); });
    chips.append(b);
  }
}
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));

/* ---------- ask / SSE ---------- */
let asking = false;
function summarize(d) {
  if (d === null || d === undefined) return "";
  if (typeof d !== "object") return clip(d, 140);
  return clip(Object.entries(d).map(([k, v]) => `${k}=${typeof v === "object" ? JSON.stringify(v) : v}`).join(", "), 160);
}
function addTrace(node, data) {
  $("trace").append(el("li", {}, el("b", {}, String(node ?? "step")), el("span", {}, "  " + summarize(data))));
}
function showError(msg) {
  $("answerbox").replaceChildren(el("div", { class: "error", role: "alert" }, el("b", {}, "Could not answer. "), document.createTextNode(String(msg))));
}

async function ask() {
  const question = $("q").value.trim();
  if (asking) return;
  if (!question) { showError("Enter a question first."); return; }
  asking = true; $("ask").disabled = true;
  $("tracebox").hidden = false; $("trace").replaceChildren(); $("answerbox").replaceChildren(); $("evidence").hidden = true;
  let got = false;
  try {
    const r = await fetch("/api/ask", { method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, mode, provider: $("provider").value || null }) });
    if (!r.ok) {
      let d = null; try { d = (await r.json()).detail; } catch (_) { /* ignore */ }
      throw new Error(typeof d === "string" ? d : `Request failed (${r.status})`);
    }
    const reader = r.body.getReader(), dec = new TextDecoder();
    let buf = "";
    const handle = (block) => {
      let ev = "message", data = "";
      for (const line of block.split("\n")) {
        if (line.startsWith("event:")) ev = line.slice(6).trim();
        else if (line.startsWith("data:")) data += line.slice(5).trim();
      }
      if (!data) return;
      const p = JSON.parse(data);
      if (ev === "trace") addTrace(p.node, p.data);
      else if (ev === "answer") { got = true; renderAnswer(p.answer || {}, p.evidence || {}); }
      else if (ev === "error") { got = true; showError(p.message); }
    };
    for (;;) {
      const { done, value } = await reader.read();
      buf += dec.decode(value || new Uint8Array(), { stream: !done });
      let i;
      while ((i = buf.indexOf("\n\n")) >= 0) { handle(buf.slice(0, i)); buf = buf.slice(i + 2); }
      if (done) break;
    }
    if (buf.trim()) handle(buf);
    if (!got) showError("The stream ended without an answer.");
  } catch (e) { showError(e.message); }
  asking = false; $("ask").disabled = false;
}
$("ask").addEventListener("click", ask);
$("q").addEventListener("keydown", (e) => { if (e.key === "Enter" && (e.ctrlKey || e.metaKey)) { e.preventDefault(); ask(); } });

/* ---------- answer ---------- */
function citedText(text, citations) {
  const frag = document.createDocumentFragment(), order = [];
  const num = (u) => { let i = order.indexOf(u); if (i < 0) i = order.push(u) - 1; return i + 1; };
  let last = 0;
  for (const m of text.matchAll(/\[(https?:\/\/[^\]\s]+)\]/g)) {
    frag.append(text.slice(last, m.index));
    const u = safeUrl(m[1]);
    if (u) frag.append(el("a", { class: "cite", href: u, target: "_blank", rel: "noopener noreferrer", title: u, "aria-label": `source ${num(u)}` }, `[${num(u)}]`));
    last = m.index + m[0].length;
  }
  frag.append(text.slice(last));
  return { frag, order };
}
function renderAnswer(a, ev) {
  const conf = ["high", "medium", "low"].includes(a.confidence) ? a.confidence : "low";
  const { frag, order } = citedText(String(a.answer ?? ""), a.citations);
  const card = el("section", { class: "answer", "aria-label": "Answer" },
    el("div", {}, el("span", { class: "badge " + conf }, `${conf} confidence`)),
    el("div", { class: "atext" }, frag));
  const extra = (a.citations || []).map(safeUrl).filter((u) => u && !order.includes(u));
  if (extra.length) {
    const p = el("div", { class: "foot" }, "Also cited: ");
    extra.forEach((u, i) => p.append(el("a", { href: u, target: "_blank", rel: "noopener noreferrer" }, clip(u, 70)), document.createTextNode(i < extra.length - 1 ? ", " : "")));
    card.append(p);
  }
  if (a.uncertainty && String(a.uncertainty).trim())
    card.append(el("div", { class: "uncertainty", role: "note" }, el("b", {}, "Not established / Uncertainty"), document.createTextNode(String(a.uncertainty))));
  else card.append(el("div", { class: "foot" }, "No uncertainty reported by the agent."));
  card.append(el("div", { class: "foot" }, `mode: ${a.mode ?? mode} | ${a.provider ?? "?"}/${a.model ?? "?"} | attempts: ${a.attempts ?? "?"}${a.prompt_version ? " | prompt " + a.prompt_version : ""}`));
  $("answerbox").replaceChildren(card);
  renderEvidence(ev);
}

/* ---------- evidence ---------- */
const KINDS = [["slack", "Slack"], ["jira", "Jira issue"], ["pr", "Pull request"], ["commit", "Commit"], ["other", "Other"]];
function kindOf(n) {  // classify by source system (id prefix), not record kind: Jira/GitHub comments are not Slack
  const id = String((n && n.id) || "");
  if (id.startsWith("slack:")) return "slack";
  if (id.startsWith("jira:")) return "jira";
  if (id.startsWith("github:")) return /:commit:/.test(id) ? "commit" : "pr";
  return "other";
}
const label = (k) => KINDS.find((x) => x[0] === k)[1];
let hlId = null;
function highlight(id, scroll) {
  hlId = hlId === id ? null : id;
  document.querySelectorAll("[data-nid]").forEach((n) => n.classList.toggle("hl", n.dataset.nid === hlId));
  document.querySelectorAll("#graph .edge").forEach((e) => e.classList.toggle("hl", hlId !== null && (e.dataset.s === hlId || e.dataset.t === hlId)));
  if (scroll && hlId) document.querySelector(`#rows [data-nid="${CSS.escape(hlId)}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
}

function renderEvidence(ev) {
  const nodes = Array.isArray(ev.nodes) ? ev.nodes : [], edges = Array.isArray(ev.edges) ? ev.edges : [];
  $("evidence").hidden = nodes.length === 0 && edges.length === 0;
  hlId = null;
  const rows = $("rows");
  rows.replaceChildren();
  const sorted = [...nodes].sort((a, b) => String(a.time || "").localeCompare(String(b.time || "")));
  for (const n of sorted) {
    const k = kindOf(n), u = safeUrl(n.url);
    const li = el("li", { class: "k-" + k, "data-nid": String(n.id), tabindex: "0" },
      el("span", { class: "kind" }, label(k)),
      el("span", { class: "time" }, String(n.time || "no timestamp")),
      el("div", {}, u ? el("a", { href: u, target: "_blank", rel: "noopener noreferrer" }, String(n.title || u)) : document.createTextNode(String(n.title || n.id))));
    if (n.text) li.append(el("div", { class: "snip" }, clip(n.text, 280)));
    if (n.via || n.hops !== undefined) li.append(el("div", { class: "snip" }, `reached ${n.hops ?? "?"} hop(s)${n.via && n.via.rel ? " via " + n.via.rel + " (" + (n.via.origin || "structural") + ")" : ""}`));
    li.addEventListener("click", (e) => { if (e.target.tagName !== "A") highlight(String(n.id), false); });
    li.addEventListener("keydown", (e) => { if (e.key === "Enter") highlight(String(n.id), false); });
    rows.append(li);
  }
  drawGraph(nodes, edges);
}

function drawGraph(nodes, edges) {
  const g = $("graph");
  g.replaceChildren();
  const W = 170, H = 34, GX = 70, GY = 14, TOP = 26;
  const cols = KINDS.map(([k]) => nodes.filter((n) => kindOf(n) === k)).map((c, i) => ({ k: KINDS[i][0], c })).filter((x) => x.c.length);
  const pos = {};
  cols.forEach((col, ci) => col.c.forEach((n, ri) => { pos[n.id] = { x: 10 + ci * (W + GX), y: TOP + ri * (H + GY) }; }));
  const rowsMax = Math.max(1, ...cols.map((c) => c.c.length));
  g.setAttribute("width", Math.max(220, 20 + cols.length * (W + GX) - GX));
  g.setAttribute("height", TOP + rowsMax * (H + GY));
  const defs = svg("defs"), mk = svg("marker", { id: "arrow", viewBox: "0 0 10 10", refX: 9, refY: 5, markerWidth: 7, markerHeight: 7, orient: "auto-start-reverse" });
  mk.append(svg("path", { d: "M0 0L10 5L0 10z" }));
  defs.append(mk); g.append(defs);
  cols.forEach((col, ci) => g.append(svg("text", { x: 10 + ci * (W + GX), y: 16, class: "colhead" }, label(col.k))));
  for (const e of edges) {
    const a = pos[e.source], b = pos[e.target];
    if (!a || !b) continue;
    const same = a.x === b.x, x1 = same ? a.x + W / 2 : a.x < b.x ? a.x + W : a.x, x2 = same ? b.x + W / 2 : a.x < b.x ? b.x : b.x + W;
    const y1 = a.y + (same ? (a.y < b.y ? H : 0) : H / 2), y2 = b.y + (same ? (a.y < b.y ? 0 : H) : H / 2);
    const line = svg("line", { x1, y1, x2, y2, class: "edge" + (e.origin === "text" ? " text" : ""), "marker-end": "url(#arrow)", "data-s": String(e.source), "data-t": String(e.target) });
    line.append(svg("title", {}, `${e.rel || "edge"} (${e.origin || "?"})${e.locator ? ": " + clip(e.locator, 120) : ""}`));
    g.append(line);
  }
  for (const n of nodes) {
    const p = pos[n.id];
    if (!p) continue;
    const k = kindOf(n);
    const grp = svg("g", { class: "node k-" + k, "data-nid": String(n.id), transform: `translate(${p.x},${p.y})`, tabindex: "0", role: "button" });
    grp.append(svg("title", {}, String(n.title || n.id)), svg("rect", { width: W, height: H, rx: 6 }), svg("text", { x: 8, y: 14 }, clip(n.title || n.id, 26)), svg("text", { x: 8, y: 27, class: "colhead" }, clip(n.time ? String(n.time).slice(0, 10) : "", 12)));
    grp.addEventListener("click", () => highlight(String(n.id), true));
    grp.addEventListener("mouseenter", () => { if (hlId !== String(n.id)) highlight(String(n.id), false); });
    grp.addEventListener("keydown", (e) => { if (e.key === "Enter") highlight(String(n.id), true); });
    g.append(grp);
  }
}

setMode("why");
loadWorkspace();
loadStatus();
