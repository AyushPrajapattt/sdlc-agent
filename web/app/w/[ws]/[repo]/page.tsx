import { Suspense } from "react";
import Empty from "@/components/Empty";
import { RepoPage } from "@/components/Gate";

async function Inner({ params }: Pick<PageProps<"/w/[ws]/[repo]">, "params">) {
  const { repo } = await params;
  return <RepoPage repo={repo} />;
}

export default function Page({ params }: PageProps<"/w/[ws]/[repo]">) {
  return <Suspense fallback={<Empty icon="spark" title="Loading…" />}><Inner params={params} /></Suspense>;
}
