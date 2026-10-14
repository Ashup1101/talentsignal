import { cn } from "@/lib/utils";

/** A circular progress ring with the percentage in the middle. */
export function ScoreRing({
  value,
  size = 128,
  stroke = 12,
  label,
  className,
}: {
  value: number; // 0..1
  size?: number;
  stroke?: number;
  label?: string;
  className?: string;
}) {
  const clamped = Math.max(0, Math.min(1, value));
  const radius = (size - stroke) / 2;
  const circumference = 2 * Math.PI * radius;
  return (
    <div className={cn("relative inline-grid place-items-center", className)} style={{ width: size, height: size }}>
      <svg width={size} height={size} viewBox={`0 0 ${size} ${size}`} className="-rotate-90" aria-hidden>
        <circle cx={size / 2} cy={size / 2} r={radius} fill="none" strokeWidth={stroke} className="stroke-muted" />
        <circle
          cx={size / 2}
          cy={size / 2}
          r={radius}
          fill="none"
          strokeWidth={stroke}
          strokeLinecap="round"
          strokeDasharray={circumference}
          strokeDashoffset={circumference * (1 - clamped)}
          className="stroke-primary transition-[stroke-dashoffset] duration-700"
        />
      </svg>
      <div className="absolute inset-0 grid place-items-center text-center" role="img" aria-label={`${Math.round(clamped * 100)}%${label ? ` ${label}` : ""}`}>
        <div>
          <div className="text-3xl font-semibold tracking-tight tabular-nums">{Math.round(clamped * 100)}%</div>
          {label && <div className="text-xs text-muted-foreground">{label}</div>}
        </div>
      </div>
    </div>
  );
}
