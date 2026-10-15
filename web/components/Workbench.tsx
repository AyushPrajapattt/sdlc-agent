"use client";
import { useEffect } from "react";
import Answer from "./Answer";
import CodePane from "./CodePane";
import Evidence from "./Evidence";
import { Provider, useWb } from "./store";

function Layout() {
  const wb = useWb();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const t = e.target as HTMLElement;
      if (t.tagName === "INPUT" || t.tagName === "TEXTAREA" || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "Escape") { wb.selectNode(null); wb.setClaim(null); }
      else if (e.key === "j") wb.stepNode(1);
      else if (e.key === "k") wb.stepNode(-1);
      else if (e.key === "1") wb.setTab("timeline");
      else if (e.key === "2") wb.setTab("graph");
      else if (e.key === "r") wb.replay();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  // keep the selected artifact in view when stepping with j/k
  useEffect(() => {
    if (wb.selected) document.querySelector(`[data-node="${wb.selected}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }, [wb.selected]);

  return (
    <div className="grid h-full grid-cols-[minmax(0,1fr)_minmax(330px,30%)] grid-rows-[minmax(0,1fr)]">
      <div className="flex min-h-0 min-w-0 flex-col">
        <CodePane />
        <Evidence />
      </div>
      <Answer />
    </div>
  );
}

export default function Workbench(props: { ws: string; repo: string; file: string; invId: string | null }) {
  return <Provider {...props}><Layout /></Provider>;
}
