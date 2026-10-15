import { notFound } from "next/navigation";
import RepoShell from "@/components/RepoShell";
import Workbench from "@/components/Workbench";
import { INVESTIGATIONS } from "@/lib/data";
import { INDEXED_REPO, WORKSPACES, repoSlug } from "@/lib/workspaces";
import { FILE_PATHS, hasPreview } from "@/lib/workspace";

export const generateStaticParams = () =>
  WORKSPACES.flatMap((w) => FILE_PATHS.map((p) => ({ ws: w.slug, repo: repoSlug(INDEXED_REPO), path: p.split("/") })));

export default async function FilePage({ params }: PageProps<"/w/[ws]/[repo]/f/[...path]">) {
  const { ws, repo, path } = await params;
  const file = path.join("/");
  if (!FILE_PATHS.includes(file)) notFound();
  if (!hasPreview(file)) return <RepoShell base={`/w/${ws}/${repo}`} icon="file" title="No preview in this mock" />;
  return <Workbench key={file} ws={ws} repo={repo} file={file} invId={INVESTIGATIONS.find((i) => i.file === file)?.id ?? null} />;
}
