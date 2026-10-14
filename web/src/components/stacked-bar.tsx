import { percent } from "@/lib/format";
import { cn } from "@/lib/utils";

export type Segment = {
  key: string;
  label: string;
  value: number;
  /** Background (and text) classes of the segment, e.g. "bg-chart-1". */
  className: string;
};

/** A 100% stacked bar in plain HTML: crisp, accessible, no chart library needed.
 *
 * Values are normalized to shares of their sum. With showValues, segments of at least
 * 10% print their share inside; every segment shows it on hover.
 */
export function StackedBar({
  segments,
  label,
  showValues = false,
  className,
}: {
  segments: Segment[];
  label: string;
  showValues?: boolean;
  className?: string;
}) {
  const total = segments.reduce((sum, s) => sum + s.value, 0) || 1;
  const shown = segments.filter((s) => s.value > 0);
  return (
    <div
      role="img"
      aria-label={`${label}: ${shown.map((s) => `${s.label} ${percent(s.value / total)}`).join(", ")}`}
      className={cn("flex overflow-hidden rounded-full", className)}
    >
      {shown.map((s) => (
        <div
          key={s.key}
          title={`${s.label}: ${percent(s.value / total)}`}
          className={cn(
            "flex min-w-0 items-center justify-center border-r-2 border-card text-[11px] font-medium tabular-nums last:border-r-0",
            s.className,
          )}
          style={{ width: `${(s.value / total) * 100}%` }}
        >
          {showValues && s.value / total >= 0.1 ? percent(s.value / total) : null}
        </div>
      ))}
    </div>
  );
}

/** Colored dots with labels, for the bars above. */
export function Legend({ items, className }: { items: { label: string; className: string }[]; className?: string }) {
  return (
    <ul className={cn("flex flex-wrap gap-x-4 gap-y-1.5 text-xs text-muted-foreground", className)}>
      {items.map((i) => (
        <li key={i.label} className="flex items-center gap-1.5">
          <span className={cn("size-2.5 rounded-full ring-1 ring-foreground/10 ring-inset", i.className)} aria-hidden />
          {i.label}
        </li>
      ))}
    </ul>
  );
}
