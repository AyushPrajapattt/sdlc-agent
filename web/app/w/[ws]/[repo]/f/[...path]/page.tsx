import { Suspense } from "react";
import Empty from "@/components/Empty";
import { FilePage } from "@/components/Gate";

async function Inner({ params }: Pick<PageProps<"/w/[ws]/[repo]/f/[...path]">, "params">) {
  const { repo, path } = await params;
  return <FilePage repo={repo} path={path.join("/")} />;
}

export default function Page({ params }: PageProps<"/w/[ws]/[repo]/f/[...path]">) {
  return <Suspense fallback={<Empty icon="spark" title="Loading…" />}><Inner params={params} /></Suspense>;
}
