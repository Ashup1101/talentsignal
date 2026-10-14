"use client";

import { Layers, Network, Wifi } from "lucide-react";
import { Bar, BarChart, CartesianGrid, XAxis, YAxis } from "recharts";

import { Kpi } from "@/components/kpi";
import { PageIntro } from "@/components/page-intro";
import { ErrorAlert, LoadingBlock } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import {
  type ChartConfig,
  ChartContainer,
  ChartLegend,
  ChartLegendContent,
  ChartTooltip,
  ChartTooltipContent,
} from "@/components/ui/chart";
import { Progress } from "@/components/ui/progress";
import { api, type Insights } from "@/lib/api";
import { LEVEL_SHORT, percent, roleLabel } from "@/lib/format";
import { useApi } from "@/lib/use-api";

const key = (s: string) => s.replace(/[^a-z0-9]+/gi, "_");
const LEVEL_ORDER = ["intern", "junior", "mid", "senior", "staff_plus", "manager", "unknown"];

export function InsightsView() {
  const insights = useApi(() => api.insights(), []);
  const data = insights.data;
  return (
    <div className="grid gap-8">
      <PageIntro title="Job Insights">
        What the postings are about beyond the five job titles we search for: topics found from the meaning of
        each posting, the roles behind them, the levels asked for and remote work.
      </PageIntro>
      {insights.error && <ErrorAlert error={insights.error} />}
      {insights.loading && !data && <LoadingBlock rows={3} />}
      {data && (
        <>
          <section className="grid gap-3 sm:grid-cols-3" aria-label="Summary">
            <Kpi icon={Network} label="Topics found" value={String(data.topics.length)} hint="re-estimated every night" />
            <Kpi icon={Layers} label="Postings in no clear topic" value={percent(data.unassigned_share)} hint="kept unassigned, not forced into one" />
            <Kpi icon={Wifi} label="Remote postings" value={percent(data.remote_share_all)} hint="of all postings" />
          </section>

          <section className="grid gap-3" aria-labelledby="topics">
            <h2 id="topics" className="text-lg font-semibold">Topics</h2>
            <p className="text-sm text-muted-foreground">
              Found by BERTopic from the meaning of each posting (shared boilerplate removed). The keywords describe
              each group; they didn&apos;t define it. Topics can shift as new postings arrive.
            </p>
            <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
              {data.topics.map((t) => (
                <Card key={t.topic_id} size="sm">
                  <CardHeader>
                    <CardTitle className="capitalize">{t.label}</CardTitle>
                    <CardDescription>
                      {t.n_postings} postings · {percent(t.share_of_postings)}
                    </CardDescription>
                  </CardHeader>
                  <CardContent className="grid gap-3">
                    <Progress value={t.share_of_postings * 100} aria-label={`${t.label} share`} />
                    <div className="flex flex-wrap gap-1">
                      {t.keywords.slice(0, 8).map((k) => (
                        <Badge key={k} variant="secondary" className="font-normal">{k}</Badge>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          </section>

          <div className="grid gap-6 lg:grid-cols-2">
            <RoleMixChart data={data} />
            <LevelMixChart data={data} />
          </div>
        </>
      )}
    </div>
  );
}

function RoleMixChart({ data }: { data: Insights }) {
  const roles = [...new Set(data.role_mix.map((m) => m.role))].sort();
  const config = Object.fromEntries(
    roles.map((r, i) => [key(r), { label: roleLabel(r), color: `var(--chart-${(i % 5) + 1})` }]),
  ) satisfies ChartConfig;
  const rows = data.topics.map((t) => ({
    topic: t.label,
    ...Object.fromEntries(
      data.role_mix.filter((m) => m.topic_id === t.topic_id).map((m) => [key(m.role), m.share_of_topic]),
    ),
  }));
  return (
    <Card>
      <CardHeader>
        <CardTitle>Which roles each topic comes from</CardTitle>
        <CardDescription>Share of each topic&apos;s postings by search role.</CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="h-96 w-full">
          <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 8 }}>
            <CartesianGrid horizontal={false} />
            <XAxis type="number" domain={[0, 1]} tickFormatter={(v: number) => percent(v)} />
            <YAxis type="category" dataKey="topic" width={150} tickLine={false} axisLine={false} />
            <ChartTooltip content={<ChartTooltipContent formatter={(v, name) => `${config[String(name)]?.label ?? name}: ${percent(Number(v))}`} />} />
            <ChartLegend content={<ChartLegendContent />} />
            {roles.map((r) => (
              <Bar key={r} dataKey={key(r)} stackId="mix" fill={`var(--color-${key(r)})`} />
            ))}
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}

function LevelMixChart({ data }: { data: Insights }) {
  const levels = LEVEL_ORDER.filter((l) => data.levels.some((c) => c.level === l));
  const config = Object.fromEntries(
    levels.map((l, i) => [l, { label: LEVEL_SHORT[l] ?? l, color: l === "unknown" ? "var(--muted-foreground)" : `var(--chart-${(i % 5) + 1})` }]),
  ) satisfies ChartConfig;
  const roles = [...new Set(data.levels.map((c) => c.role))].sort();
  const rows = roles.map((r) => {
    const counts = data.levels.filter((c) => c.role === r);
    const total = counts.reduce((sum, c) => sum + c.n_postings, 0);
    return { role: roleLabel(r), ...Object.fromEntries(counts.map((c) => [c.level, c.n_postings / total])) };
  });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Level asked for, by role</CardTitle>
        <CardDescription>From the job title when it states a level, otherwise from the years of experience asked for.</CardDescription>
      </CardHeader>
      <CardContent>
        <ChartContainer config={config} className="h-96 w-full">
          <BarChart data={rows} layout="vertical" margin={{ left: 8, right: 8 }}>
            <CartesianGrid horizontal={false} />
            <XAxis type="number" domain={[0, 1]} tickFormatter={(v: number) => percent(v)} />
            <YAxis type="category" dataKey="role" width={150} tickLine={false} axisLine={false} />
            <ChartTooltip content={<ChartTooltipContent formatter={(v, name) => `${config[String(name)]?.label ?? name}: ${percent(Number(v))}`} />} />
            <ChartLegend content={<ChartLegendContent />} />
            {levels.map((l) => (
              <Bar key={l} dataKey={l} stackId="levels" fill={`var(--color-${l})`} />
            ))}
          </BarChart>
        </ChartContainer>
      </CardContent>
    </Card>
  );
}
