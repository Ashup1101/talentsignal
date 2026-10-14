"use client";

import { Layers, Network, Wifi } from "lucide-react";

import { Kpi } from "@/components/kpi";
import { PageIntro } from "@/components/page-intro";
import { Legend, StackedBar } from "@/components/stacked-bar";
import { ErrorAlert, LoadingBlock } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { type Insights, api } from "@/lib/api";
import { LEVEL_SHORT, percent, roleLabel } from "@/lib/format";
import { useApi } from "@/lib/use-api";

/** "ml, machine learning, models" → "Ml, machine learning, models" (keep keywords as written). */
const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

const ROLE_COLORS = ["bg-chart-1", "bg-chart-2", "bg-chart-3", "bg-chart-4", "bg-chart-5"];

/** Levels are ordered, so they get one hue from light to dark; manager and "not stated" stand apart. */
const LEVEL_COLORS: Record<string, string> = {
  intern: "bg-primary/15 text-foreground",
  junior: "bg-primary/30 text-foreground",
  mid: "bg-primary/50 text-foreground",
  senior: "bg-primary/80 text-white dark:text-primary-foreground",
  staff_plus: "bg-primary text-primary-foreground",
  manager: "bg-chart-3 text-neutral-900",
  unknown: "bg-muted-foreground/25 text-foreground",
};
const LEVEL_ORDER = Object.keys(LEVEL_COLORS);

/** One color per search role, the same on every bar of the page. */
function roleColors(data: Insights): Map<string, string> {
  const roles = [...new Set([...data.role_mix, ...data.levels, ...data.remote].map((r) => r.role))].sort();
  return new Map(roles.map((r, i) => [r, ROLE_COLORS[i % ROLE_COLORS.length]]));
}

export function InsightsView() {
  const insights = useApi(() => api.insights(), []);
  const data = insights.data;
  return (
    <div className="grid gap-8">
      <PageIntro title="Job Insights" icon={Network} tone="rose">
        What the postings are about beyond the five job titles we search for: topics found from the meaning of
        each posting, the roles behind them, the levels asked for and remote work.
      </PageIntro>
      {insights.error && <ErrorAlert error={insights.error} />}
      {insights.loading && !data && <LoadingBlock rows={3} />}
      {data && (
        <>
          <section className="grid gap-3 sm:grid-cols-3" aria-label="Summary">
            <Kpi icon={Network} tone="rose" label="Topics found" value={String(data.topics.length)} hint="re-estimated every night" />
            <Kpi icon={Layers} tone="sky" label="Postings in no clear topic" value={percent(data.unassigned_share)} hint="kept unassigned, not forced into one" />
            <Kpi icon={Wifi} tone="teal" label="Remote postings" value={percent(data.remote_share_all)} hint="of all postings" />
          </section>
          <Topics data={data} />
          <div className="grid gap-6 lg:grid-cols-3">
            <LevelMix data={data} />
            <RemoteByRole data={data} />
          </div>
        </>
      )}
    </div>
  );
}

function Topics({ data }: { data: Insights }) {
  const colors = roleColors(data);
  return (
    <section className="grid gap-4" aria-labelledby="topics">
      <div className="grid gap-1.5">
        <h2 id="topics" className="text-lg font-semibold">Topics</h2>
        <p className="text-sm text-muted-foreground">
          Found by BERTopic from the meaning of each posting (shared boilerplate removed). The keywords describe
          each group; they didn&apos;t define it. Topics can shift as new postings arrive. Each bar shows which
          search roles the topic&apos;s postings came from.
        </p>
        <Legend items={[...colors].map(([role, className]) => ({ label: roleLabel(role), className }))} />
      </div>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {data.topics.map((t) => {
          const mix = data.role_mix.filter((m) => m.topic_id === t.topic_id).sort((a, b) => b.share_of_topic - a.share_of_topic);
          const top = mix[0];
          return (
            <Card key={t.topic_id} size="sm">
              <CardHeader>
                <CardTitle className="leading-snug">{sentence(t.label)}</CardTitle>
                <CardDescription>
                  {t.n_postings} postings · {percent(t.share_of_postings)} of all
                </CardDescription>
              </CardHeader>
              <CardContent className="grid gap-3">
                <div className="grid gap-1.5">
                  <StackedBar
                    className="h-2"
                    label={`Roles behind "${t.label}"`}
                    segments={mix.map((m) => ({
                      key: m.role,
                      label: roleLabel(m.role),
                      value: m.share_of_topic,
                      className: colors.get(m.role) ?? "bg-muted-foreground",
                    }))}
                  />
                  {top && (
                    <div className="text-xs text-muted-foreground">
                      {top.share_of_topic >= 0.5
                        ? `Mostly ${roleLabel(top.role)} postings (${percent(top.share_of_topic)})`
                        : "A mix of roles"}
                    </div>
                  )}
                </div>
                <div className="flex flex-wrap gap-1">
                  {t.keywords.slice(0, 8).map((k) => (
                    <Badge key={k} variant="secondary" className="font-normal">{k}</Badge>
                  ))}
                </div>
              </CardContent>
            </Card>
          );
        })}
      </div>
    </section>
  );
}

function LevelMix({ data }: { data: Insights }) {
  const levels = LEVEL_ORDER.filter((l) => data.levels.some((c) => c.level === l));
  const roles = [...new Set(data.levels.map((c) => c.role))].sort();
  return (
    <Card className="lg:col-span-2">
      <CardHeader>
        <CardTitle>Level asked for, by role</CardTitle>
        <CardDescription>From the job title when it states a level, otherwise from the years of experience asked for.</CardDescription>
        <Legend className="pt-1" items={levels.map((l) => ({ label: LEVEL_SHORT[l] ?? l, className: LEVEL_COLORS[l] }))} />
      </CardHeader>
      <CardContent className="grid gap-3">
        {roles.map((r) => (
          <div key={r} className="grid grid-cols-[6.5rem_1fr] items-center gap-3 sm:grid-cols-[11rem_1fr]">
            <div className="text-sm leading-tight font-medium">{roleLabel(r)}</div>
            <StackedBar
              className="h-7 rounded-md"
              showValues
              label={`Levels in ${roleLabel(r)} postings`}
              segments={levels.map((l) => ({
                key: l,
                label: LEVEL_SHORT[l] ?? l,
                value: data.levels.find((c) => c.role === r && c.level === l)?.n_postings ?? 0,
                className: LEVEL_COLORS[l],
              }))}
            />
          </div>
        ))}
      </CardContent>
    </Card>
  );
}

function RemoteByRole({ data }: { data: Insights }) {
  // Scale to the highest share rounded up to the next 10%, so small differences stay visible;
  // the scale is printed below so a full bar never reads as "all postings".
  const scale = Math.min(1, Math.ceil(Math.max(...data.remote.map((r) => r.share), 0.01) * 10) / 10);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Remote work, by role</CardTitle>
        <CardDescription>Share of each role&apos;s postings marked remote. All roles: {percent(data.remote_share_all)}.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {[...data.remote].sort((a, b) => b.share - a.share).map((r) => (
          <div key={r.role} className="grid gap-1.5">
            <div className="flex items-baseline justify-between gap-2 text-sm">
              <span className="font-medium">{roleLabel(r.role)}</span>
              <span className="tabular-nums text-muted-foreground">{percent(r.share)}</span>
            </div>
            <div className="h-1.5 overflow-hidden rounded-full bg-muted" aria-hidden>
              <div className="h-full rounded-full bg-chart-2" style={{ width: `${(r.share / scale) * 100}%` }} />
            </div>
          </div>
        ))}
        <p className="text-xs text-muted-foreground">Bars run from 0% to {percent(scale)}.</p>
      </CardContent>
    </Card>
  );
}
