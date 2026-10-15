import { notFound } from "next/navigation";
import Workbench from "@/components/Workbench";
import { INVESTIGATIONS } from "@/lib/data";
import { INDEXED_REPO, WORKSPACES, repoSlug } from "@/lib/workspaces";

export const generateStaticParams = () =>
  WORKSPACES.flatMap((w) => INVESTIGATIONS.map((i) => ({ ws: w.slug, repo: repoSlug(INDEXED_REPO), id: i.id })));

export default async function WhyPage({ params }: PageProps<"/w/[ws]/[repo]/why/[id]">) {
  const { ws, repo, id } = await params;
  const inv = INVESTIGATIONS.find((i) => i.id === id);
  if (!inv) notFound();
  return <Workbench key={id} ws={ws} repo={repo} file={inv.file} invId={inv.id} />;
}
