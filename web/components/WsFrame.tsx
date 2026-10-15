"use client";
import type { ReactNode } from "react";
import { isWs, Ready, Unknown } from "./Gate";
import LeftPane from "./LeftPane";
import { useLocation } from "./Shell";

export default function WsFrame({ children }: { children: ReactNode }) {
  const { ws } = useLocation();
  if (!isWs(ws)) return <Unknown what="workspace" />;
  return (
    <Ready>
      <div className="flex h-full">
        <LeftPane ws={ws!} />
        <div className="min-w-0 flex-1">{children}</div>
      </div>
    </Ready>
  );
}
