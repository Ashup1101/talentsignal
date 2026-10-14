"use client";

import { Hourglass } from "lucide-react";
import { useState } from "react";
import { Area, Bar, BarChart, CartesianGrid, ComposedChart, Line, XAxis, YAxis } from "recharts";

import { LabeledSelect } from "@/components/labeled-select";
import { PageIntro } from "@/components/page-intro";
import { ErrorAlert, LoadingBlock } from "@/components/states";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { type ChartConfig, ChartContainer, ChartTooltip, ChartTooltipContent } from "@/components/ui/chart";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { api } from "@/lib/api";
import { percent, roleLabel } from "@/lib/format";
import { useApi } from "@/lib/use-api";

const TOP_N = 12;
const shareConfig = { share: { label: "Share of postings", color: "var(--chart-2)" } } satisfies ChartConfig;
const forecastConfig = {
  share: { label: "Observed", color: "var(--chart-1)" },
  forecast: { label: "Forecast", color: "var(--chart-2)" },
  band: { label: "95% interval", color: "var(--chart-2)" },
} satisfies ChartConfig;

export function SkillsView() {
  const options = useApi(() => api.options(), []);
  const [role, setRole] = useState<string | null>(null);
  const roles = options.data?.roles ?? [];
  const chosen = role ?? (roles.includes("data engineer") ? "data engineer" : roles[0] ?? null);
  const demand = useApi(() => (chosen ? api.skills(chosen) : Promise.resolve(undefined)), [chosen]);
  const data = demand.data;

  return (
    <div className="grid gap-8">
      <PageIntro title="Skill Demand">
        How often each role&apos;s postings mention each skill, and where demand is heading once enough weeks of
        postings are collected.
      </PageIntro>
      <LabeledSelect
        id="role"
        label="Role"
        value={chosen}
        options={roles.map((r) => ({ value: r, label: roleLabel(r) }))}
        onChange={(v) => v && setRole(v)}
      />
      {(options.error ?? demand.error) && <ErrorAlert error={(options.error ?? demand.error)!} />}
      {demand.loading && !data && <LoadingBlock rows={2} />}
      {data && (
        <>
          <div className="grid gap-6 lg:grid-cols-[3fr_2fr]">
            <Card>
              <CardHeader>
                <CardTitle>What {roleLabel(data.role)} postings ask for</CardTitle>
                <CardDescription>Top {TOP_N} skills by share of the role&apos;s {data.n_role_postings.toLocaleString("en-US")} postings.</CardDescription>
              </CardHeader>
              <CardContent>
                <ChartContainer config={shareConfig} className="h-96 w-full">
                  <BarChart data={data.skills.slice(0, TOP_N)} layout="vertical" margin={{ left: 8, right: 16 }}>
                    <CartesianGrid horizontal={false} />
                    <XAxis type="number" domain={[0, 1]} tickFormatter={(v: number) => percent(v)} />
                    <YAxis type="category" dataKey="skill" width={120} tickLine={false} axisLine={false} />
                    <ChartTooltip content={<ChartTooltipContent formatter={(v) => percent(Number(v))} />} />
                    <Bar dataKey="share_of_postings" name="share" fill="var(--color-share)" radius={4} />
                  </BarChart>
                </ChartContainer>
              </CardContent>
            </Card>
            <ForecastCard role={data.role} status={data.forecast} />
          </div>
          <Card>
            <CardHeader>
              <CardTitle>All skills, ranked</CardTitle>
            </CardHeader>
            <CardContent>
              <Table>
                <TableHeader>
                  <TableRow>
                    <TableHead className="w-14">Rank</TableHead>
                    <TableHead>Skill</TableHead>
                    <TableHead className="hidden sm:table-cell">Category</TableHead>
                    <TableHead className="w-1/3">Share of postings</TableHead>
                    <TableHead className="text-right">Postings</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {data.skills.map((s) => (
                    <TableRow key={s.skill}>
                      <TableCell className="tabular-nums text-muted-foreground">{s.rank}</TableCell>
                      <TableCell className="font-medium">{s.skill}</TableCell>
                      <TableCell className="hidden capitalize text-muted-foreground sm:table-cell">{s.category.replaceAll("_", " ")}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2">
                          <Progress value={s.share_of_postings * 100} className="flex-1" aria-label={`${s.skill} share`} />
                          <span className="w-10 text-right text-xs tabular-nums">{percent(s.share_of_postings)}</span>
                        </div>
                      </TableCell>
                      <TableCell className="text-right tabular-nums">{s.postings}</TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </CardContent>
          </Card>
        </>
      )}
    </div>
  );
}

function ForecastCard({
  role,
  status,
}: {
  role: string;
  status: { weeks_observed: number; weeks_needed: number; forecasting_skills: string[] };
}) {
  const [skill, setSkill] = useState<string | null>(null);
  const chosen = skill ?? status.forecasting_skills[0] ?? null;
  const series = useApi(() => (chosen ? api.forecast(role, chosen) : Promise.resolve(undefined)), [role, chosen]);
  const points = [
    ...(series.data?.history ?? []).map((p) => ({ week: p.week, share: p.share })),
    ...(series.data?.forecast ?? []).map((p) => ({ week: p.week, forecast: p.share, band: [p.lower, p.upper] })),
  ];
  return (
    <Card>
      <CardHeader>
        <CardTitle>Demand forecast</CardTitle>
        <CardDescription>Prophet, linear trend, 90 days ahead — once a skill has enough weekly data.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div className="grid gap-2">
          <div className="flex justify-between text-sm">
            <span>Weekly collections</span>
            <span className="tabular-nums text-muted-foreground">
              {status.weeks_observed} of {status.weeks_needed}
            </span>
          </div>
          <Progress value={Math.min(100, (100 * status.weeks_observed) / status.weeks_needed)} aria-label="Weeks collected" />
        </div>
        {status.forecasting_skills.length === 0 ? (
          <Alert>
            <Hourglass aria-hidden />
            <AlertDescription>
              Forecasts start once a skill has {status.weeks_needed} weekly data points; the nightly pipeline adds
              about one a week. Until then, the shares on this page are the current picture.
            </AlertDescription>
          </Alert>
        ) : (
          <>
            <LabeledSelect
              id="forecast-skill"
              label="Skill"
              value={chosen}
              options={status.forecasting_skills.map((s) => ({ value: s, label: s }))}
              onChange={(v) => v && setSkill(v)}
            />
            {series.error && <ErrorAlert error={series.error} />}
            {series.data && (
              <ChartContainer config={forecastConfig} className="h-64 w-full">
                <ComposedChart data={points} margin={{ left: 8, right: 8 }}>
                  <CartesianGrid vertical={false} />
                  <XAxis dataKey="week" tickLine={false} minTickGap={24} />
                  <YAxis tickFormatter={(v: number) => percent(v)} width={44} />
                  <ChartTooltip content={<ChartTooltipContent />} />
                  <Area dataKey="band" fill="var(--color-band)" fillOpacity={0.2} stroke="none" />
                  <Line dataKey="share" stroke="var(--color-share)" dot={false} strokeWidth={2} />
                  <Line dataKey="forecast" stroke="var(--color-forecast)" strokeDasharray="5 4" dot={false} strokeWidth={2} />
                </ComposedChart>
              </ChartContainer>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
