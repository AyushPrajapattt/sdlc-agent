import { notFound } from "next/navigation";
import LeftPane from "@/components/LeftPane";
import { WORKSPACES } from "@/lib/workspaces";

export const generateStaticParams = () => WORKSPACES.map((w) => ({ ws: w.slug }));

export default async function WorkspaceLayout({ children, params }: LayoutProps<"/w/[ws]">) {
  const { ws } = await params;
  if (!WORKSPACES.some((w) => w.slug === ws)) notFound();
  return (
    <div className="flex h-full">
      <LeftPane ws={ws} />
      <div className="min-w-0 flex-1">{children}</div>
    </div>
  );
}
