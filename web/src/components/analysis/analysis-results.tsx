"use client";

import { CheckCircle2, CircleDollarSign, ExternalLink, Gauge, ListChecks, Sparkles, XCircle } from "lucide-react";

import { Kpi } from "@/components/kpi";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Progress } from "@/components/ui/progress";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Analysis } from "@/lib/api";
import {
  impactText,
  levelLabel,
  medianDifferenceText,
  money,
  percent,
  roleLabel,
  windowText,
} from "@/lib/format";
import { cn } from "@/lib/utils";

export function AnalysisResults({ analysis, sample = false }: { analysis: Analysis; sample?: boolean }) {
  const role = roleLabel(analysis.role);
  const best = analysis.role_matches[0];
  const onResume = analysis.core_skills.filter((s) => s.on_resume).length;
  return (
    <div className="grid gap-6">
      {sample && (
        <Alert>
          <Sparkles aria-hidden />
          <AlertDescription>Showing results for the sample resume, a made-up data engineer.</AlertDescription>
        </Alert>
      )}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4" aria-label="Summary">
        <Kpi icon={Gauge} label="Best match" value={best ? percent(best.match) : "—"} hint={best ? roleLabel(best.role) : undefined} />
        <Kpi icon={CircleDollarSign} label={`Estimated salary, ${role}`} value={money(analysis.salary.estimate)} hint={`${money(analysis.salary.low)} – ${money(analysis.salary.high)}`} />
        <Kpi icon={ListChecks} label="Skills found" value={String(analysis.skills.length)} hint="from our ~110-skill dictionary" />
        <Kpi icon={CheckCircle2} label={`${role} core skills`} value={`${onResume} / ${analysis.core_skills.length}`} hint="in ≥ 10% of its postings" />
      </section>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Match by role</CardTitle>
            <CardDescription>Share of each role&apos;s core skills on your resume, weighted by how often postings ask for them.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-3">
            {analysis.role_matches.map((m) => (
              <div key={m.role} className="grid gap-1">
                <div className="flex justify-between text-sm">
                  <span className={cn(m.role === analysis.role && "font-medium")}>{roleLabel(m.role)}</span>
                  <span className="tabular-nums text-muted-foreground">{percent(m.match)}</span>
                </div>
                <Progress value={m.match * 100} aria-label={`${roleLabel(m.role)} match`} />
              </div>
            ))}
          </CardContent>
        </Card>

        <SalaryCard analysis={analysis} />
      </div>

      <div className="grid gap-6 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Skills found</CardTitle>
            <CardDescription>With how often {role} postings mention each one.</CardDescription>
          </CardHeader>
          <CardContent className="flex flex-wrap gap-2">
            {analysis.skills.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No skills from our dictionary were found. If your resume is a scanned image, its text can&apos;t be read.
              </p>
            )}
            {analysis.skills.map((s) => (
              <Tooltip key={s.skill}>
                <TooltipTrigger render={<span />}>
                  <Badge variant={s.share_of_role_postings >= 0.25 ? "default" : s.share_of_role_postings > 0 ? "secondary" : "outline"}>
                    {s.skill}
                    <span className="ml-1 tabular-nums opacity-70">{percent(s.share_of_role_postings)}</span>
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>
                  In {percent(s.share_of_role_postings)} of {role} postings
                </TooltipContent>
              </Tooltip>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>{role} core skills</CardTitle>
            <CardDescription>The skills in at least 10% of the role&apos;s postings, most asked-for first.</CardDescription>
          </CardHeader>
          <CardContent>
            <ul className="grid gap-1.5 sm:grid-cols-2">
              {analysis.core_skills.map((s) => (
                <li key={s.skill} className="flex items-center gap-2 text-sm">
                  {s.on_resume ? (
                    <CheckCircle2 className="size-4 text-emerald-600" aria-label="on your resume" />
                  ) : (
                    <XCircle className="size-4 text-muted-foreground" aria-label="not on your resume" />
                  )}
                  <span className={cn(!s.on_resume && "text-muted-foreground")}>{s.skill}</span>
                  <span className="ml-auto tabular-nums text-xs text-muted-foreground">{percent(s.share_of_role_postings)}</span>
                </li>
              ))}
            </ul>
          </CardContent>
        </Card>
      </div>

      <section className="grid gap-3" aria-labelledby="skills-to-add">
        <div>
          <h2 id="skills-to-add" className="text-lg font-semibold">Top skills to add</h2>
          <p className="text-sm text-muted-foreground">
            The most in-demand {role} skills missing from your resume. Salary figures are associations in posted
            salaries, not promises: postings that ask for a skill can differ in other ways too.
          </p>
        </div>
        {analysis.missing_skills.length === 0 ? (
          <p className="text-sm text-muted-foreground">Your resume covers every skill these postings ask for.</p>
        ) : (
          <div className="grid gap-3 md:grid-cols-3">
            {analysis.missing_skills.map((m) => (
              <Card key={m.skill} size="sm">
                <CardHeader>
                  <CardTitle>{m.skill}</CardTitle>
                  <CardDescription>In {percent(m.share_of_role_postings)} of {role} postings</CardDescription>
                </CardHeader>
                <CardContent className="grid gap-2 text-sm">
                  <div>
                    <div className="text-muted-foreground">Salary model what-if</div>
                    <div className="font-medium">{impactText(m.model_impact_status, m.model_impact)}</div>
                  </div>
                  <div>
                    <div className="text-muted-foreground">Median posted salary, with vs without it</div>
                    <div className="font-medium">
                      {medianDifferenceText(m.median_difference_status, m.median_salary_difference, m.n_salaried_with_skill, m.n_salaried_without_skill)}
                    </div>
                  </div>
                </CardContent>
              </Card>
            ))}
          </div>
        )}
      </section>

      <PostingsCard analysis={analysis} />
    </div>
  );
}

function SalaryCard({ analysis }: { analysis: Analysis }) {
  const { salary } = analysis;
  const role = roleLabel(analysis.role);
  const level = levelLabel(analysis.level);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Estimated salary</CardTitle>
        <CardDescription>
          {salary.method === "model"
            ? "From the XGBoost model trained on posted salaries."
            : "The model didn't beat this simple median in testing, so the estimate is the role median."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <div>
          <div className="text-3xl font-semibold tracking-tight tabular-nums">{money(salary.estimate)}</div>
          <div className="text-sm text-muted-foreground">
            Likely range {money(salary.low)} – {money(salary.high)} (± the model&apos;s typical error for this role,{" "}
            {money(salary.typical_error)})
          </div>
        </div>
        <dl className="grid gap-2 text-sm">
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">
              Posted median, {role}
              {analysis.level !== "unknown" && <>, {level.toLowerCase()}</>}
            </dt>
            <dd className="text-right font-medium tabular-nums">
              {salary.level_median.status === "ok"
                ? `${money(salary.level_median.median)} (${salary.level_median.n} postings)`
                : salary.level_median.status === "no_level"
                  ? "choose your level to see it"
                  : `too few salaries (${salary.level_median.n})`}
            </dd>
          </div>
          <div className="flex justify-between gap-4">
            <dt className="text-muted-foreground">Posted median, all {role} postings</dt>
            <dd className="font-medium tabular-nums">{money(salary.role_median)}</dd>
          </div>
        </dl>
        <p className="text-xs text-muted-foreground">
          Estimated from salaries posted in job ads (mostly large U.S. metros), not from offers or pay surveys. When
          the estimate and the median for your level differ a lot, trust the median: the model has few junior salaries
          to learn from.
        </p>
      </CardContent>
    </Card>
  );
}

function PostingsCard({ analysis }: { analysis: Analysis }) {
  const { postings } = analysis;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Matching job postings</CardTitle>
        <CardDescription>
          {windowText(postings.window, postings.since)} Postings near your level come first; ranked by similarity of
          meaning, not just shared keywords.
        </CardDescription>
      </CardHeader>
      <CardContent>
        {postings.items.length === 0 ? (
          <p className="text-sm text-muted-foreground">No postings for this role yet.</p>
        ) : (
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Job</TableHead>
                <TableHead>Level</TableHead>
                <TableHead className="hidden md:table-cell">Shared skills</TableHead>
                <TableHead className="text-right">Match</TableHead>
                <TableHead className="w-10"><span className="sr-only">Apply</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {postings.items.map((p) => (
                <TableRow key={p.job_id}>
                  <TableCell className="max-w-72 whitespace-normal">
                    <div className="font-medium">{p.title}</div>
                    <div className="text-xs text-muted-foreground">
                      {[p.employer, p.location].filter(Boolean).join(" · ")}
                      {p.remote && " · Remote"}
                    </div>
                  </TableCell>
                  <TableCell>
                    <Badge variant={p.near_level ? "secondary" : "outline"}>{levelLabel(p.level)}</Badge>
                  </TableCell>
                  <TableCell className="hidden max-w-80 whitespace-normal md:table-cell">
                    <div className="flex flex-wrap gap-1">
                      {p.shared_skills.slice(0, 6).map((s) => (
                        <Badge key={s} variant="outline" className="font-normal">{s}</Badge>
                      ))}
                      {p.shared_skills.length > 6 && (
                        <span className="text-xs text-muted-foreground">+{p.shared_skills.length - 6}</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="text-right tabular-nums">{percent(p.similarity)}</TableCell>
                  <TableCell>
                    {p.apply_link && (
                      <a
                        href={p.apply_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`Open the posting: ${p.title}`}
                        className="text-muted-foreground hover:text-foreground"
                      >
                        <ExternalLink className="size-4" aria-hidden />
                      </a>
                    )}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        )}
      </CardContent>
    </Card>
  );
}
