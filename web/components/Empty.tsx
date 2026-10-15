import type { ReactNode } from "react";
import { Icon, type IconName } from "./icons";

export default function Empty({ icon, title, children }: { icon: IconName; title: string; children?: ReactNode }) {
  return (
    <div className="flex h-full items-center justify-center p-8 text-center">
      <div>
        <div className="mx-auto mb-3 grid h-10 w-10 place-items-center rounded-full border border-line2 text-dim"><Icon name={icon} size={17} /></div>
        <p className="font-medium">{title}</p>
        {children && <div className="mt-3">{children}</div>}
      </div>
    </div>
  );
}
