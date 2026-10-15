import { Suspense } from "react";
import Empty from "@/components/Empty";
import { WhyPage } from "@/components/Gate";

async function Inner({ params }: Pick<PageProps<"/w/[ws]/[repo]/why/[id]">, "params">) {
  const { repo, id } = await params;
  return <WhyPage repo={repo} id={id} />;
}

export default function Page({ params }: PageProps<"/w/[ws]/[repo]/why/[id]">) {
  return <Suspense fallback={<Empty icon="spark" title="Loading…" />}><Inner params={params} /></Suspense>;
}
