import type { LucideIcon } from "lucide-react";

import { IconTile, type Tone } from "@/components/icon-tile";
import { Card, CardContent } from "@/components/ui/card";

export function Kpi({
  label,
  value,
  hint,
  icon,
  tone = "indigo",
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: LucideIcon;
  tone?: Tone;
}) {
  return (
    <Card>
      <CardContent className="flex items-start gap-3">
        {icon && <IconTile icon={icon} tone={tone} />}
        <div className="grid min-w-0 gap-0.5">
          <div className="text-sm text-muted-foreground">{label}</div>
          <div className="truncate text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
          {hint && <div className="truncate text-xs text-muted-foreground">{hint}</div>}
        </div>
      </CardContent>
    </Card>
  );
}
