import WorkspaceEmpty from "@/components/WorkspaceEmpty";

export default async function WorkspacePage({ params }: PageProps<"/w/[ws]">) {
  const { ws } = await params;
  return <WorkspaceEmpty ws={ws} />;
}
