"use client";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { Fragment, createContext, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { INVESTIGATIONS } from "@/lib/data";
import { CATALOG, INDEXED_REPO, WORKSPACES, repoSlug } from "@/lib/workspaces";
import { FILE_PATHS } from "@/lib/workspace";
import ConfigDialog from "./ConfigDialog";
import { Icon, type IconName } from "./icons";

const Manage = createContext<(ws: string) => void>(() => {});
export const useManage = () => useContext(Manage);

/** Parse /w/[ws]/[repo]/(f|why)/... into its parts. */
export function useLocation() {
  const path = usePathname();
  const [, w, ws, repo, kind, ...rest] = path.split("/");
  return { ws: w === "w" ? ws : undefined, repo, file: kind === "f" ? rest.join("/") : kind === "why" ? INVESTIGATIONS.find((i) => i.id === rest[0])?.file : undefined };
}

function useTheme() {
  const [theme, set] = useState<"light" | "dark">("dark");
  useEffect(() => { set(document.documentElement.dataset.theme === "light" ? "light" : "dark"); }, []);
  const toggle = () => {
    const next = theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = next;
    try { localStorage.setItem("wb-theme", next); } catch {}
    set(next);
  };
  return [theme, toggle] as const;
}

function Switcher({ onManage }: { onManage: (ws: string) => void }) {
  const { ws } = useLocation();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const cur = WORKSPACES.find((w) => w.slug === ws);
  useEffect(() => {
    const on = (e: MouseEvent) => { if (!ref.current?.contains(e.target as Node)) setOpen(false); };
    document.addEventListener("mousedown", on);
    return () => document.removeEventListener("mousedown", on);
  }, []);

  return (
    <div ref={ref} className="relative">
      <button onClick={() => setOpen((o) => !o)} aria-haspopup="menu" aria-expanded={open}
        className="flex h-8 items-center gap-2 rounded-md pl-1.5 pr-2 hover:bg-hover">
        {cur && <span className="grid h-5 w-5 place-items-center rounded bg-fg text-[11px] font-semibold text-bg">{cur.name[0]}</span>}
        <span className="font-medium">{cur?.name ?? "Workspaces"}</span>
        <Icon name="updown" size={12} className="text-dim" />
      </button>
      {open && (
        <div role="menu" className="fade-up absolute left-0 top-9 z-40 w-56 rounded-lg border border-line2 bg-bg p-1 shadow-xl shadow-black/20">
          {WORKSPACES.map((w) => (
            <Link key={w.slug} href={`/w/${w.slug}`} onClick={() => setOpen(false)} role="menuitem"
              className="flex h-8 items-center gap-2 rounded-md px-2 hover:bg-hover">
              <span className="grid h-5 w-5 place-items-center rounded bg-raised text-[11px] font-semibold">{w.name[0]}</span>
              {w.name}{w.slug === ws && <Icon name="check" size={13} className="ml-auto text-dim" />}
            </Link>
          ))}
          <div className="my-1 border-t border-line" />
          {cur && (
            <button onClick={() => { setOpen(false); onManage(cur.slug); }} role="menuitem" className="flex h-8 w-full items-center gap-2 rounded-md px-2 text-left text-mute hover:bg-hover hover:text-fg">
              <Icon name="sliders" size={13} />Connections
            </button>
          )}
          <Link href="/" onClick={() => setOpen(false)} role="menuitem" className="flex h-8 items-center gap-2 rounded-md px-2 text-mute hover:bg-hover hover:text-fg">
            <Icon name="home" size={13} />All workspaces
          </Link>
        </div>
      )}
    </div>
  );
}

function Topbar({ onPalette, onManage }: { onPalette: () => void; onManage: (ws: string) => void }) {
  const { ws, repo, file } = useLocation();
  const [theme, toggle] = useTheme();
  const parts = file?.split("/") ?? [];
  return (
    <header className="flex h-12 shrink-0 items-center gap-1.5 border-b border-line px-3">
      <Link href="/" aria-label="All workspaces" className="grid h-8 w-8 place-items-center rounded-md hover:bg-hover">
        <svg width="18" height="18" viewBox="0 0 20 20" aria-hidden>
          <path d="M5 14 10 5l5 9M5 14h10" stroke="var(--fg)" strokeWidth="1.3" fill="none" strokeLinejoin="round" opacity=".55" />
          <circle cx="10" cy="5" r="2.2" fill="#8b5cf6" /><circle cx="5" cy="14" r="2.2" fill="#f97316" /><circle cx="15" cy="14" r="2.2" fill="#3b82f6" />
        </svg>
      </Link>
      <span className="text-line2">/</span>
      <Switcher onManage={onManage} />
      {ws && repo && (
        <nav aria-label="Location" className="flex min-w-0 items-center gap-1.5 text-[12.5px]">
          <span className="text-line2">/</span>
          <Link href={`/w/${ws}/${repo}`} className={`font-medium ${parts.length ? "text-mute hover:text-fg" : ""}`}>{repo}</Link>
          {parts.map((p, i) => (
            <Fragment key={i}><span className="text-line2">/</span><span className={`truncate font-mono text-[12px] ${i === parts.length - 1 ? "text-fg" : "text-dim"}`}>{p}</span></Fragment>
          ))}
        </nav>
      )}
      <div className="ml-auto flex items-center gap-1.5">
        <button onClick={onPalette} className="flex h-8 items-center gap-2 rounded-md border border-line bg-bg pl-2.5 pr-1.5 text-dim hover:border-line2 hover:text-mute">
          <Icon name="search" size={13} />Search<span className="kbd">Ctrl K</span>
        </button>
        <button onClick={toggle} aria-label="Toggle theme" className="grid h-8 w-8 place-items-center rounded-md text-dim hover:bg-hover hover:text-fg">
          <Icon name={theme === "dark" ? "sun" : "moon"} size={14} />
        </button>
      </div>
    </header>
  );
}

interface Item { group: string; label: string; hint?: string; icon: IconName; href: string }

function Palette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const { ws } = useLocation();
  const base = `/w/${ws ?? "acme"}/${repoSlug(INDEXED_REPO)}`;
  const [q, setQ] = useState("");
  const [i, setI] = useState(0);
  useEffect(() => { if (open) { setQ(""); setI(0); } }, [open]);

  const items = useMemo<Item[]>(() => {
    const all: Item[] = [
      ...INVESTIGATIONS.map((v) => ({ group: "Questions", label: v.question, hint: v.file.split("/").pop(), icon: "help" as const, href: `${base}/why/${v.id}` })),
      ...WORKSPACES.map((w) => ({ group: "Workspaces", label: w.name, icon: "home" as const, href: `/w/${w.slug}` })),
      ...CATALOG.repos.map((r) => ({ group: "Repositories", label: r, icon: "repo" as const, href: `/w/${ws ?? "acme"}/${repoSlug(r)}` })),
      ...FILE_PATHS.map((p) => ({ group: "Files", label: p, icon: "file" as const, href: `${base}/f/${p}` })),
    ];
    const s = q.trim().toLowerCase();
    return (s ? all.filter((x) => x.label.toLowerCase().includes(s)) : all.filter((x) => x.group !== "Files")).slice(0, 30);
  }, [q, base, ws]);

  if (!open) return null;
  const go = (it?: Item) => { if (it) { router.push(it.href); onClose(); } };
  return (
    <div className="fixed inset-0 z-50 grid place-items-start justify-center bg-black/40 pt-[14vh] backdrop-blur-[2px]" onMouseDown={onClose}>
      <div role="dialog" aria-label="Search" onMouseDown={(e) => e.stopPropagation()}
        className="fade-up w-[540px] max-w-[92vw] overflow-hidden rounded-xl border border-line2 bg-bg shadow-2xl shadow-black/30">
        <div className="flex items-center gap-2 border-b border-line px-3">
          <Icon name="search" size={14} className="text-dim" />
          <input autoFocus value={q} onChange={(e) => { setQ(e.target.value); setI(0); }} placeholder="Search files, questions, repos…"
            onKeyDown={(e) => {
              if (e.key === "ArrowDown") { e.preventDefault(); setI((x) => Math.min(items.length - 1, x + 1)); }
              if (e.key === "ArrowUp") { e.preventDefault(); setI((x) => Math.max(0, x - 1)); }
              if (e.key === "Enter") go(items[i]);
              if (e.key === "Escape") onClose();
            }}
            className="h-11 flex-1 bg-transparent text-[13.5px] outline-none placeholder:text-dim" />
        </div>
        <ul className="max-h-[340px] overflow-auto p-1.5">
          {items.length === 0 && <li className="p-4 text-center text-dim">No results</li>}
          {items.map((it, n) => (
            <li key={it.group + it.href}>
              {(n === 0 || items[n - 1].group !== it.group) && <div className="label px-2 pb-1 pt-2.5">{it.group}</div>}
              <button onClick={() => go(it)} onMouseMove={() => setI(n)}
                className={`flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left ${n === i ? "bg-raised text-fg" : "text-mute"}`}>
                <Icon name={it.icon} size={13} className="text-dim" /><span className="truncate">{it.label}</span>
                {it.hint && <span className="ml-auto shrink-0 font-mono text-[11px] text-dim">{it.hint}</span>}
              </button>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}

export default function Shell({ children }: { children: ReactNode }) {
  const [palette, setPalette] = useState(false);
  const [manage, setManage] = useState<string | null>(null);
  useEffect(() => {
    const on = (e: KeyboardEvent) => { if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") { e.preventDefault(); setPalette((p) => !p); } };
    window.addEventListener("keydown", on);
    return () => window.removeEventListener("keydown", on);
  }, []);
  return (
    <Manage.Provider value={setManage}>
      <div className="flex h-screen min-w-[1000px] flex-col">
        <Topbar onPalette={() => setPalette(true)} onManage={setManage} />
        <main className="min-h-0 flex-1">{children}</main>
      </div>
      <Palette open={palette} onClose={() => setPalette(false)} />
      {manage && <ConfigDialog ws={manage} onClose={() => setManage(null)} />}
    </Manage.Provider>
  );
}
