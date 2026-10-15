import WsFrame from "@/components/WsFrame";

// Data is live and client-driven: nothing here reads params or the backend, so the shell stays static.
export default function WorkspaceLayout({ children }: LayoutProps<"/w/[ws]">) {
  return <WsFrame>{children}</WsFrame>;
}
