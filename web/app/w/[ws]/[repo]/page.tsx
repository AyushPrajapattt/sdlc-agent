import RepoShell from "@/components/RepoShell";
import { CATALOG, INDEXED_REPO, WORKSPACES, repoSlug } from "@/lib/workspaces";

export const generateStaticParams = () => WORKSPACES.flatMap((w) => CATALOG.repos.map((r) => ({ ws: w.slug, repo: repoSlug(r) })));

export default async function RepoPage({ params }: PageProps<"/w/[ws]/[repo]">) {
  const { ws, repo } = await params;
  const indexed = repo === repoSlug(INDEXED_REPO);
  return <RepoShell base={`/w/${ws}/${repo}`} icon="file" title={indexed ? "Select a file" : "Indexing…"} />;
}
