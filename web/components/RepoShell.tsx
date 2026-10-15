import type { ReactNode } from "react";
import { InvestigationList } from "./Answer";
import Empty from "./Empty";
import type { IconName } from "./icons";

/** Centre message + investigations on the right, for repo-level pages with no open file. */
export default function RepoShell({ base, icon, title }: { base: string; icon: IconName; title: ReactNode }) {
  return (
    <div className="grid h-full grid-cols-[minmax(0,1fr)_minmax(330px,30%)]">
      <Empty icon={icon} title={String(title)} />
      <aside className="border-l border-line p-3" aria-label="Investigations">
        <div className="label mb-2 px-3 pt-1">Investigations</div>
        <InvestigationList base={base} />
      </aside>
    </div>
  );
}
