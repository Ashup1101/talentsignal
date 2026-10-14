"use client";

import { ArrowRight, Briefcase, CalendarClock, CircleDollarSign, Database, FileSearch, Sparkles, Target } from "lucide-react";
import Link from "next/link";

import { Kpi } from "@/components/kpi";
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
  { icon: Database, title: "Real postings, every night", text: "Airflow collects postings for five data and software roles, cleans them with PySpark and models them with dbt." },
  { icon: Sparkles, title: "NLP and machine learning", text: "Skills come from one shared dictionary; years of experience and topics from NLP; salaries from an XGBoost model." },
  { icon: Target, title: "Your resume, compared", text: "Your resume is read with the same dictionary and the same embedding model as the postings — and never stored." },
];

const PAGE_TEXT: Record<string, string> = {
  "/analyze/": "Skills, match by role, salary estimate, skills to add, matching postings.",
  "/salaries/": "Posted salary ranges by role, level and state, next to BLS medians.",
  "/skills/": "What each role asks for, ranked, and the demand forecast's progress.",
  "/insights/": "Topics in the postings, the roles behind them, levels and remote work.",
};

export function HomeView() {
  const overview = useApi(() => api.overview(), []);
  return (
    <div className="grid gap-10">
      <section className="grid gap-5 pt-4">
        <Badge variant="secondary" className="w-fit">Resume intelligence from real job postings</Badge>
        <h1 className="max-w-3xl text-4xl font-semibold tracking-tight sm:text-5xl">
          How does your resume compare with what employers actually ask for?
        </h1>
        <p className="max-w-2xl text-lg text-muted-foreground">
          Upload a resume to see the skills it shows, your match with five data and software roles, an estimated
          salary, the in-demand skills you&apos;re missing, and matching postings collected this week.
        </p>
        <div className="flex flex-wrap gap-3">
          <Link href="/analyze/" className={cn(buttonVariants({ size: "lg" }), "gap-2")}>
            <FileSearch className="size-4" aria-hidden /> Analyze my resume
          </Link>
          <Link href="/salaries/" className={buttonVariants({ size: "lg", variant: "outline" })}>
            Explore salaries
          </Link>
        </div>
      </section>

      <section className="grid gap-4" aria-labelledby="freshness">
        <div className="flex items-center justify-between">
          <h2 id="freshness" className="text-lg font-semibold">The data right now</h2>
          {overview.data && (
            <Badge variant={overview.data.pipeline_current ? "secondary" : "destructive"}>
              {overview.data.pipeline_current ? "Pipeline current" : "Pipeline behind: newest postings are over 2 days old"}
            </Badge>
          )}
        </div>
        {overview.loading && <LoadingBlock rows={1} />}
        {overview.error && <ErrorAlert error={overview.error} />}
        {overview.data && (
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
            <Kpi icon={Briefcase} label="Job postings" value={overview.data.n_postings.toLocaleString("en-US")} hint={`${overview.data.n_salaried} with a posted salary`} />
            <Kpi icon={CalendarClock} label="Newest collection" value={ageText(overview.data.newest_collection)} hint={`${overview.data.n_last_7_days} postings in the last 7 days`} />
            <Kpi icon={CircleDollarSign} label="Salary model error" value={money(overview.data.model_typical_error)} hint="typical (cross-validated MAE)" />
            <Card size="sm">
              <CardContent className="grid gap-2">
                <div className="text-sm text-muted-foreground">Demand forecast</div>
                <div className="text-2xl font-semibold tabular-nums">
                  {overview.data.forecast_weeks_observed} / {overview.data.forecast_weeks_needed} weeks
                </div>
                <Progress value={(100 * overview.data.forecast_weeks_observed) / overview.data.forecast_weeks_needed} />
                <div className="text-xs text-muted-foreground">Forecasts start at {overview.data.forecast_weeks_needed} weekly collections</div>
              </CardContent>
            </Card>
          </div>
        )}
      </section>

      <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4" aria-label="Pages">
        {NAV.map(({ href, label, icon: Icon }) => (
          <Link key={href} href={href} className="group">
            <Card className="h-full transition-shadow group-hover:shadow-md">
              <CardHeader>
                <CardTitle className="flex items-center gap-2">
                  <Icon className="size-4 text-primary" aria-hidden /> {label}
                  <ArrowRight className="ml-auto size-4 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden />
                </CardTitle>
                <CardDescription>{PAGE_TEXT[href]}</CardDescription>
              </CardHeader>
            </Card>
          </Link>
        ))}
      </section>

      <section className="grid gap-4 md:grid-cols-3" aria-label="How it works">
        {STEPS.map(({ icon: Icon, title, text }) => (
          <div key={title} className="grid gap-2">
            <Icon className="size-5 text-primary" aria-hidden />
            <h3 className="font-medium">{title}</h3>
            <p className="text-sm text-muted-foreground">{text}</p>
          </div>
        ))}
      </section>
    </div>
  );
}
