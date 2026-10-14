import type { LucideIcon } from "lucide-react";

import { IconTile, type Tone } from "@/components/icon-tile";

export function PageIntro({
  title,
  icon,
  tone = "indigo",
  children,
}: {
  title: string;
  icon?: LucideIcon;
  tone?: Tone;
  children: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-4">
      {icon && <IconTile icon={icon} tone={tone} className="mt-1 size-11" />}
      <div className="grid gap-2">
        <h1 className="text-3xl font-semibold tracking-tight">{title}</h1>
        <p className="max-w-3xl text-pretty text-muted-foreground">{children}</p>
      </div>
    </div>
  );
}
