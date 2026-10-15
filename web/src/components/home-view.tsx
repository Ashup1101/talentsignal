"use client";

import { ArrowRight, Briefcase, CalendarClock, CircleDollarSign, Database, FileSearch, Hourglass, Sparkles, Target } from "lucide-react";
import Link from "next/link";

import { IconTile, type Tone } from "@/components/icon-tile";
import { Kpi } from "@/components/kpi";
import { SalaryScale } from "@/components/salary-scale";
import { ScoreRing } from "@/components/score-ring";
import { NAV } from "@/components/site-header";
import { ErrorAlert, LoadingBlock } from "@/components/states";
import { Badge } from "@/components/ui/badge";
import { buttonVariants } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { api } from "@/lib/api";
import { ageText, money } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

const STEPS = [
  { icon: Database, tone: "indigo", title: "Real postings, every night", text: "Airflow collects postings for five data and software roles, cleans them with PySpark and models them with dbt." },
  { icon: Sparkles, tone: "teal", title: "NLP and machine learning", text: "Skills from one shared dictionary; years of experience and topics from NLP; salaries from an XGBoost model." },
  { icon: Target, tone: "amber", title: "Your resume, compared", text: "Read with the same dictionary and the same embedding model as the postings — and never stored." },
] satisfies { icon: typeof Database; tone: Tone; title: string; text: string }[];

const PAGE_TEXT: Record<string, { text: string; tone: Tone }> = {
  "/analyze/": { text: "Skills, match by role, salary estimate, skills to add, matching postings.", tone: "indigo" },
  "/salaries/": { text: "Posted salary ranges by role, level and state, next to BLS medians.", tone: "teal" },
  "/skills/": { text: "What each role asks for, ranked, and the demand forecast's progress.", tone: "amber" },
  "/insights/": { text: "Topics in the postings, the roles behind them, levels and remote work.", tone: "rose" },
};

export function HomeView() {
  const overview = useApi(() => api.overview(), []);
  return (
    <div className="grid gap-12">
      <section className="bg-hero-glow grid items-center gap-10 rounded-3xl border bg-card px-6 py-10 shadow-sm sm:px-10 lg:grid-cols-[1.15fr_0.85fr] lg:py-14">
        <div className="grid gap-6">
          <Badge variant="secondary" className="w-fit gap-1.5">
            <Sparkles className="size-3.5" aria-hidden /> Resume intelligence from real job postings
          </Badge>
          <h1 className="text-4xl font-semibold tracking-tight text-balance sm:text-5xl">
            How does your resume compare with what employers{" "}
            <span className="bg-gradient-to-r from-chart-1 to-chart-2 bg-clip-text text-transparent">actually ask for</span>?
          </h1>
          <p className="max-w-xl text-lg text-pretty text-muted-foreground">
            See the skills your resume shows, your match with five data and software roles, an estimated salary, the
            in-demand skills you&apos;re missing, and matching postings collected this week.
          </p>
          <div className="flex flex-wrap gap-3">
            <Link href="/analyze/" className={cn(buttonVariants({ size: "lg" }), "gap-2 px-5")}>
              <FileSearch className="size-4" aria-hidden /> Analyze my resume
            </Link>
            <Link href="/salaries/" className={cn(buttonVariants({ size: "lg", variant: "outline" }), "px-5")}>
              Explore salaries
            </Link>
          </div>
          <p className="text-xs text-muted-foreground">Free · no sign-up · your resume is never stored</p>
        </div>
        <ExampleCard />
      </section>

      <section className="grid gap-4" aria-labelledby="freshness">
        <div className="flex flex-wrap items-center justify-between gap-2">
          <h2 id="freshness" className="text-xl font-semibold tracking-tight">The data right now</h2>
          {overview.data && (
            <Badge variant={overview.data.pipeline_current ? "secondary" : "destructive"} className="gap-1.5">
              <span className={cn("size-1.5 rounded-full", overview.data.pipeline_current ? "bg-success" : "bg-current")} />
              {overview.data.pipeline_current ? "Pipeline current" : "Pipeline behind: newest postings are over 2 days old"}
            </Badge>
          )}
        </div>
        {overview.loading && !overview.data && <LoadingBlock rows={1} />}
        {overview.error && <ErrorAlert error={overview.error} />}
        {overview.data && (
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi icon={Briefcase} tone="indigo" label="Job postings" value={overview.data.n_postings.toLocaleString("en-US")} hint={`${overview.data.n_salaried} with a posted salary`} />
            <Kpi icon={CalendarClock} tone="teal" label="Newest collection" value={ageText(overview.data.newest_collection)} hint={`${overview.data.n_last_7_days} postings in the last 7 days`} />
            <Kpi icon={CircleDollarSign} tone="amber" label="Salary model error" value={money(overview.data.model_typical_error)} hint="typical (cross-validated MAE)" />
            <Card>
              <CardContent className="flex items-start gap-3">
                <IconTile icon={Hourglass} tone="rose" />
                <div className="grid flex-1 gap-1.5">
                  <div className="text-sm text-muted-foreground">Demand forecast</div>
                  <div className="text-2xl font-semibold tracking-tight tabular-nums">
                    {overview.data.forecast_weeks_observed}
                    <span className="text-base text-muted-foreground"> / {overview.data.forecast_weeks_needed} weeks</span>
                  </div>
                  <Progress value={(100 * overview.data.forecast_weeks_observed) / overview.data.forecast_weeks_needed} aria-label="Forecast progress" />
                </div>
              </CardContent>
            </Card>
          </div>
        )}
      </section>

      <section className="grid gap-4" aria-labelledby="explore">
        <h2 id="explore" className="text-xl font-semibold tracking-tight">Explore</h2>
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
          {NAV.map(({ href, label, icon }) => (
            <Link key={href} href={href} className="group">
              <Card className="h-full transition-all group-hover:-translate-y-0.5 group-hover:shadow-md group-hover:ring-primary/30">
                <CardHeader className="gap-3">
                  <IconTile icon={icon} tone={PAGE_TEXT[href].tone} />
                  <CardTitle className="flex items-center gap-1">
                    {label}
                    <ArrowRight className="size-4 -translate-x-1 opacity-0 transition-all group-hover:translate-x-0 group-hover:opacity-100" aria-hidden />
                  </CardTitle>
                  <CardDescription>{PAGE_TEXT[href].text}</CardDescription>
                </CardHeader>
              </Card>
            </Link>
          ))}
        </div>
      </section>

      <section className="grid gap-6 rounded-3xl border bg-card p-6 sm:p-10 md:grid-cols-3" aria-label="How it works">
        {STEPS.map(({ icon, tone, title, text }, i) => (
          <div key={title} className="grid content-start gap-3">
            <div className="flex items-center gap-3">
              <IconTile icon={icon} tone={tone} />
              <span className="text-xs font-medium text-muted-foreground">Step {i + 1}</span>
            </div>
            <h3 className="font-semibold">{title}</h3>
            <p className="text-sm text-muted-foreground">{text}</p>
          </div>
        ))}
      </section>
    </div>
  );
}

/** A static, clearly labelled example of the analysis — what a visitor will get. */
function ExampleCard() {
  return (
    <Card className="relative shadow-xl ring-primary/10" aria-label="Example result">
      <CardHeader className="flex-row items-center justify-between">
        <CardTitle className="text-sm text-muted-foreground">Example result · Data Engineer</CardTitle>
        <Badge variant="outline">Example</Badge>
      </CardHeader>
      <CardContent className="grid gap-6">
        <div className="flex items-center gap-5">
          <ScoreRing value={0.73} size={112} stroke={11} label="match" />
          <div className="grid gap-2 text-sm">
            <div className="font-medium">Strong overlap with core skills</div>
            <div className="flex flex-wrap gap-1.5">
              {["SQL", "Python", "Spark", "Airflow"].map((s) => (
                <Badge key={s} className="gap-1 bg-success/15 text-success hover:bg-success/15">{s}</Badge>
              ))}
            </div>
            <div className="flex flex-wrap gap-1.5">
              {["Databricks", "Snowflake"].map((s) => (
                <Badge key={s} variant="outline" className="text-muted-foreground">+ {s}</Badge>
              ))}
            </div>
          </div>
        </div>
        <SalaryScale
          low={132_000}
          high={187_000}
          markers={[
            { label: "Your estimate", value: 159_000, tone: "primary" },
            { label: "Posted median, your level", value: 150_000, tone: "teal" },
            { label: "Posted median, the role", value: 163_000, tone: "amber" },
          ]}
        />
      </CardContent>
    </Card>
  );
}
