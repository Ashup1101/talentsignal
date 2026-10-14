"use client";

import { useState } from "react";

import { LabeledSelect } from "@/components/labeled-select";
import { PageIntro } from "@/components/page-intro";
import { ErrorAlert, LoadingBlock } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api, type SalaryBand } from "@/lib/api";
import { money, roleLabel } from "@/lib/format";
import { useApi } from "@/lib/use-api";

export function SalariesView() {
  const options = useApi(() => api.options(), []);
  const [level, setLevel] = useState<string | null>(null);
  const [state, setState] = useState<string | null>(null);
  const bands = useApi(() => api.salaries(level, state), [level, state]);
  const shown = (bands.data ?? []).filter((b) => b.status === "ok");
  const tooFew = (bands.data ?? []).filter((b) => b.status !== "ok");

  return (
    <div className="grid gap-8">
      <PageIntro title="Salary Explorer">
        Salaries posted in job ads (the midpoint of each posted range, per year) by role, next to the national
        median from the U.S. Bureau of Labor Statistics (BLS).
      </PageIntro>
      <div className="flex flex-wrap gap-4">
        <LabeledSelect
          id="level"
          label="Level"
          value={level}
          noneLabel="All levels"
          options={(options.data?.levels ?? []).filter((l) => l.value !== "unknown").map((l) => ({ value: l.value, label: l.label }))}
          onChange={setLevel}
        />
        <LabeledSelect
          id="state"
          label="State"
          value={state}
          noneLabel="All states"
          options={(options.data?.states ?? []).map((s) => ({ value: s, label: s }))}
          onChange={setState}
        />
      </div>

      {bands.error && <ErrorAlert error={bands.error} />}
      {bands.loading && !bands.data && <LoadingBlock rows={2} />}
      {bands.data && (
        <>
          <Card>
            <CardHeader>
              <CardTitle>Posted salary ranges</CardTitle>
              <CardDescription>
                Bar: the middle half of posted salaries (25th–75th percentile). Line: median. Diamond: BLS median.
              </CardDescription>
            </CardHeader>
            <CardContent>
              {shown.length === 0 ? (
                <p className="text-sm text-muted-foreground">
                  Fewer than 5 posted salaries for every role with these filters; try a broader selection.
                </p>
              ) : (
                <RangeChart bands={shown} />
              )}
            </CardContent>
          </Card>

          {shown.length > 0 && (
            <Card>
              <CardContent>
                <Table>
                  <TableHeader>
                    <TableRow>
                      <TableHead>Role</TableHead>
                      <TableHead className="text-right">Posted salaries</TableHead>
                      <TableHead className="text-right">25th percentile</TableHead>
                      <TableHead className="text-right">Median</TableHead>
                      <TableHead className="text-right">75th percentile</TableHead>
                      <TableHead className="text-right">BLS median</TableHead>
                      <TableHead className="text-right">Median vs BLS</TableHead>
                    </TableRow>
                  </TableHeader>
                  <TableBody>
                    {shown.map((b) => (
                      <TableRow key={b.role}>
                        <TableCell className="font-medium">{roleLabel(b.role)}</TableCell>
                        <TableCell className="text-right tabular-nums">{b.n_salaries}</TableCell>
                        <TableCell className="text-right tabular-nums">{money(b.p25)}</TableCell>
                        <TableCell className="text-right tabular-nums">{money(b.median)}</TableCell>
                        <TableCell className="text-right tabular-nums">{money(b.p75)}</TableCell>
                        <TableCell className="text-right tabular-nums">{money(b.bls_median)}</TableCell>
                        <TableCell className="text-right tabular-nums">
                          {b.median_vs_bls === null || b.median_vs_bls === undefined
                            ? "—"
                            : `${b.median_vs_bls >= 0 ? "+" : ""}${Math.round(b.median_vs_bls * 100)}%`}
                        </TableCell>
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </CardContent>
            </Card>
          )}

          {tooFew.length > 0 && (
            <p className="text-sm text-muted-foreground">
              Too few posted salaries (under 5) to report:{" "}
              {tooFew.map((b) => `${roleLabel(b.role)} (${b.n_salaries})`).join(", ")}.
            </p>
          )}
          <p className="text-xs text-muted-foreground">
            Posted salaries run above BLS medians: the postings come from five large metros and lean senior, while
            BLS covers every employer nationwide. Data analyst has no BLS benchmark (no matching occupation code).
          </p>
        </>
      )}
    </div>
  );
}

/** A bullet-style range chart in plain HTML: crisp, accessible, no chart library needed. */
export function RangeChart({ bands }: { bands: SalaryBand[] }) {
  const values = bands.flatMap((b) => [b.p25, b.p75, b.bls_median]).filter((v): v is number => typeof v === "number");
  const low = Math.floor(Math.min(...values) / 25_000) * 25_000;
  const high = Math.ceil(Math.max(...values) / 25_000) * 25_000;
  const x = (v: number) => `${((v - low) / (high - low)) * 100}%`;
  const ticks = Array.from({ length: (high - low) / 25_000 + 1 }, (_, i) => low + i * 25_000);
  return (
    <div className="grid gap-4" role="img" aria-label="Posted salary ranges by role">
      {bands.map((b) => (
        <div key={b.role} className="grid grid-cols-[minmax(0,11rem)_1fr] items-center gap-3">
          <div className="truncate text-sm">{roleLabel(b.role)}</div>
          <div className="relative h-7 rounded-md bg-muted/50">
            {b.p25 !== null && b.p75 !== null && b.p25 !== undefined && b.p75 !== undefined && (
              <div
                className="absolute top-1 bottom-1 rounded bg-chart-2/70"
                style={{ left: x(b.p25), width: `calc(${x(b.p75)} - ${x(b.p25)})` }}
                title={`${money(b.p25)} – ${money(b.p75)}`}
              />
            )}
            {typeof b.median === "number" && (
              <div className="absolute top-0 bottom-0 w-0.5 bg-foreground" style={{ left: x(b.median) }} title={`Median ${money(b.median)}`} />
            )}
            {typeof b.bls_median === "number" && (
              <div
                className="absolute top-1/2 size-3 -translate-x-1/2 -translate-y-1/2 rotate-45 bg-chart-1 ring-2 ring-background"
                style={{ left: x(b.bls_median) }}
                title={`BLS median ${money(b.bls_median)}`}
              />
            )}
          </div>
        </div>
      ))}
      <div className="grid grid-cols-[minmax(0,11rem)_1fr] gap-3">
        <div />
        <div className="relative h-4 text-xs text-muted-foreground">
          {ticks.map((t) => (
            <span key={t} className="absolute -translate-x-1/2 tabular-nums" style={{ left: x(t) }}>
              ${Math.round(t / 1000)}K
            </span>
          ))}
        </div>
      </div>
    </div>
  );
}
