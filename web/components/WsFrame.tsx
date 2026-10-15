"use client";
import type { ReactNode } from "react";
import { Ready } from "./Gate";
import LeftPane from "./LeftPane";
import { useLocation } from "./Shell";

export default function WsFrame({ children }: { children: ReactNode }) {
  const { ws, repo } = useLocation();
  return (
    <Ready>
      <div className="flex h-full">
        {repo !== "setup" && <LeftPane ws={ws!} />}
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </Ready>
  );
}
