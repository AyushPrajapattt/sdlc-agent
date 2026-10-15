import { Suspense } from "react";
import Empty from "@/components/Empty";
import Setup from "@/components/Setup";

export default function Page() {
  return <Suspense fallback={<Empty icon="spark" title="Loading…" />}><Setup /></Suspense>;
}
