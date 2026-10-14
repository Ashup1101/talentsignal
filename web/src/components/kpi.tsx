import type { LucideIcon } from "lucide-react";

import { Card, CardContent } from "@/components/ui/card";

export function Kpi({
  label,
  value,
  hint,
  icon: Icon,
}: {
  label: string;
  value: string;
  hint?: string;
  icon?: LucideIcon;
}) {
  return (
    <Card size="sm">
      <CardContent className="grid gap-1">
        <div className="flex items-center gap-2 text-sm text-muted-foreground">
          {Icon && <Icon className="size-4" aria-hidden />}
          {label}
        </div>
        <div className="text-2xl font-semibold tracking-tight tabular-nums">{value}</div>
        {hint && <div className="text-xs text-muted-foreground">{hint}</div>}
      </CardContent>
    </Card>
  );
}
