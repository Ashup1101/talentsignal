import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

const TONES = {
  indigo: "bg-chart-1/12 text-chart-1",
  teal: "bg-chart-2/15 text-chart-2",
  amber: "bg-chart-3/20 text-[color-mix(in_oklch,var(--chart-3)_70%,black)] dark:text-chart-3",
  rose: "bg-chart-4/12 text-chart-4",
  sky: "bg-chart-5/15 text-chart-5",
} as const;

export type Tone = keyof typeof TONES;

/** An icon in a tinted rounded square: the visual anchor of cards and steps. */
export function IconTile({ icon: Icon, tone = "indigo", className }: { icon: LucideIcon; tone?: Tone; className?: string }) {
  return (
    <span className={cn("inline-flex size-9 shrink-0 items-center justify-center rounded-lg", TONES[tone], className)}>
      <Icon className="size-[18px]" aria-hidden />
    </span>
  );
}
