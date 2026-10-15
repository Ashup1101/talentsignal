import { money } from "@/lib/format";

export interface ScaleMarker {
  label: string;
  value: number;
  tone: "primary" | "teal" | "amber";
}

const MARKER = {
  primary: "bg-primary ring-primary/25",
  teal: "bg-chart-2 ring-chart-2/25",
  amber: "bg-chart-3 ring-chart-3/30",
} as const;

/**
 * One horizontal scale: the likely range as a band, the estimate and reference medians
 * as dots — so "estimate vs what postings at your level pay" is visible at a glance.
 */
export function SalaryScale({ low, high, markers }: { low: number; high: number; markers: ScaleMarker[] }) {
  const values = [low, high, ...markers.map((m) => m.value)];
  const min = Math.floor((Math.min(...values) * 0.92) / 10_000) * 10_000;
  const max = Math.ceil((Math.max(...values) * 1.05) / 10_000) * 10_000;
  const x = (v: number) => `${((v - min) / (max - min)) * 100}%`;
  return (
    <div className="grid gap-3">
      <div className="relative h-10" role="img" aria-label={markers.map((m) => `${m.label} ${money(m.value)}`).join(", ")}>
        <div className="absolute inset-x-0 top-1/2 h-2 -translate-y-1/2 rounded-full bg-muted" />
        <div
          className="absolute top-1/2 h-2 -translate-y-1/2 rounded-full bg-primary/25"
          style={{ left: x(low), width: `calc(${x(high)} - ${x(low)})` }}
          title={`Likely range ${money(low)} – ${money(high)}`}
        />
        {markers.map((m) => (
          <div
            key={m.label}
            className={`absolute top-1/2 size-4 -translate-x-1/2 -translate-y-1/2 rounded-full ring-4 ${MARKER[m.tone]}`}
            style={{ left: x(m.value) }}
            title={`${m.label}: ${money(m.value)}`}
          />
        ))}
      </div>
      <div className="flex justify-between text-xs tabular-nums text-muted-foreground">
        <span>{money(min)}</span>
        <span>{money(max)}</span>
      </div>
      <ul className="grid gap-1.5 text-sm">
        {markers.map((m) => (
          <li key={m.label} className="flex items-center gap-2">
            <span className={`size-2.5 rounded-full ${MARKER[m.tone].split(" ")[0]}`} aria-hidden />
            <span className="text-muted-foreground">{m.label}</span>
            <span className="ml-auto font-medium tabular-nums">{money(m.value)}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
