import type { ReactNode } from "react";

// Shared control styles: the owner's existing button / input look, named once.
export const field = "h-8 min-w-0 flex-1 rounded-md border border-line bg-bg px-2 font-mono text-[12px] outline-none placeholder:text-dim focus:border-line2 disabled:opacity-50";
export const btnPrimary = "inline-flex h-8 items-center justify-center gap-1.5 rounded-md bg-fg px-4 text-[12.5px] font-medium text-bg hover:opacity-90 disabled:opacity-40";
export const btnAccent = "inline-flex h-8 items-center justify-center gap-1.5 rounded-md bg-accent px-4 text-[12.5px] font-medium text-bg hover:opacity-90 disabled:opacity-40";
export const btnGhost = "inline-flex h-8 items-center justify-center gap-1.5 rounded-md border border-line px-3 text-[12.5px] text-mute hover:border-line2 hover:text-fg disabled:opacity-40";

export function Spinner() {
  return <span aria-hidden className="h-3 w-3 shrink-0 animate-spin rounded-full border-[1.5px] border-current border-t-transparent" />;
}

/** Label above/beside an input; the input is wrapped so the label is programmatically associated. */
export function Field({ label, children, hint }: { label: string; children: ReactNode; hint?: string }) {
  return (
    <label className="flex flex-col gap-1 text-[11.5px] text-dim">
      <span>{label}</span>
      <span className="flex">{children}</span>
      {hint && <span className="sr-only">{hint}</span>}
    </label>
  );
}

export const errText = (e: unknown) => (e instanceof Error ? e.message : "Request failed");

/** Inline result line, announced to screen readers. */
export function Notice({ tone, children }: { tone: "ok" | "warn" | "dim"; children: ReactNode }) {
  return <p role={tone === "warn" ? "alert" : "status"} className={`text-[12px] ${tone === "ok" ? "text-ok" : tone === "warn" ? "text-warn" : "text-dim"}`}>{children}</p>;
}

export function Chip({ tone, children }: { tone: "ok" | "warn" | "bad" | "dim" | "run"; children: ReactNode }) {
  const c = { ok: "text-ok", warn: "text-warn", bad: "text-bad", dim: "text-dim", run: "text-accent" }[tone];
  return <span className={`inline-flex items-center gap-1 rounded-full border border-line px-2 text-[11px] leading-[18px] ${c}`}>{children}</span>;
}
