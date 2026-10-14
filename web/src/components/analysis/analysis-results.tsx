"use client";

import { CheckCircle2, ExternalLink, ListChecks, Sparkles, Target, TrendingUp } from "lucide-react";

import { IconTile } from "@/components/icon-tile";
import { SalaryScale, type ScaleMarker } from "@/components/salary-scale";
import { ScoreRing } from "@/components/score-ring";
import { Alert, AlertDescription } from "@/components/ui/alert";
import { Badge } from "@/components/ui/badge";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import type { Analysis } from "@/lib/api";
import { impactText, levelLabel, medianDifferenceText, money, percent, roleLabel, windowText } from "@/lib/format";
import { cn } from "@/lib/utils";

const MISSING_SHOWN = 12;

export function AnalysisResults({ analysis, sample = false }: { analysis: Analysis; sample?: boolean }) {
  return (
    <div className="grid gap-6">
      {sample && (
        <Alert>
          <Sparkles aria-hidden />
          <AlertDescription>Showing results for the sample resume, a made-up data engineer.</AlertDescription>
        </Alert>
      )}
      <SummaryCard analysis={analysis} />
      <div className="grid gap-6 xl:grid-cols-2">
        <MatchCard analysis={analysis} />
        <SalaryCard analysis={analysis} />
      </div>
      <SkillsCard analysis={analysis} />
      <SkillsToAdd analysis={analysis} />
      <PostingsCard analysis={analysis} />
    </div>
  );
}

function SummaryCard({ analysis }: { analysis: Analysis }) {
  const role = roleLabel(analysis.role);
  const target = analysis.role_matches.find((m) => m.role === analysis.role);
  const best = analysis.role_matches[0];
  const onResume = analysis.core_skills.filter((s) => s.on_resume).length;
  return (
    <Card className="bg-hero-glow">
      <CardContent className="flex flex-col items-center gap-6 sm:flex-row">
        <ScoreRing value={target?.match ?? 0} label="match" />
        <div className="grid flex-1 gap-3 text-center sm:text-left">
          <div>
            <div className="text-sm text-muted-foreground">Your match with</div>
            <div className="text-2xl font-semibold tracking-tight">{role}</div>
          </div>
          <div className="flex flex-wrap justify-center gap-2 sm:justify-start">
            <Badge variant="secondary">{onResume} of {analysis.core_skills.length} core skills</Badge>
            <Badge variant="secondary">{analysis.skills.length} skills found</Badge>
            {best && best.role !== analysis.role && (
              <Badge variant="outline" className="gap-1">
                <TrendingUp className="size-3" aria-hidden /> Best fit: {roleLabel(best.role)} ({percent(best.match)})
              </Badge>
            )}
          </div>
        </div>
        <div className="grid gap-0.5 text-center sm:text-right">
          <div className="text-sm text-muted-foreground">Estimated salary</div>
          <div className="text-3xl font-semibold tracking-tight tabular-nums">{money(analysis.salary.estimate)}</div>
          <div className="text-xs text-muted-foreground">
            {money(analysis.salary.low)} – {money(analysis.salary.high)}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function MatchCard({ analysis }: { analysis: Analysis }) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Match by role</CardTitle>
        <CardDescription>Share of each role&apos;s core skills on your resume, weighted by how often postings ask for them.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        {analysis.role_matches.map((m) => {
          const target = m.role === analysis.role;
          return (
            <div key={m.role} className="grid gap-1.5">
              <div className="flex items-center justify-between text-sm">
                <span className={cn("flex items-center gap-1.5", target && "font-medium")}>
                  {roleLabel(m.role)}
                  {target && <Badge variant="secondary" className="h-5 px-1.5 text-[10px]">target</Badge>}
                </span>
                <span className="font-medium tabular-nums">{percent(m.match)}</span>
              </div>
              <div className="h-2.5 overflow-hidden rounded-full bg-muted" role="img" aria-label={`${roleLabel(m.role)} match ${percent(m.match)}`}>
                <div className={cn("h-full rounded-full", target ? "bg-primary" : "bg-chart-5/60")} style={{ width: `${m.match * 100}%` }} />
              </div>
            </div>
          );
        })}
      </CardContent>
    </Card>
  );
}

function SalaryCard({ analysis }: { analysis: Analysis }) {
  const { salary } = analysis;
  const role = roleLabel(analysis.role);
  const level = levelLabel(analysis.level).toLowerCase();
  const markers: ScaleMarker[] = [{ label: "Your estimate", value: salary.estimate, tone: "primary" }];
  if (salary.level_median.status === "ok" && salary.level_median.median !== null && salary.level_median.median !== undefined) {
    markers.push({ label: `Posted median, ${role}, ${level} (${salary.level_median.n} postings)`, value: salary.level_median.median, tone: "teal" });
  }
  markers.push({ label: `Posted median, all ${role} postings`, value: salary.role_median, tone: "amber" });
  return (
    <Card>
      <CardHeader>
        <CardTitle>Estimated salary</CardTitle>
        <CardDescription>
          {salary.method === "model"
            ? `XGBoost model trained on posted salaries; the band is ± its typical error for this role (${money(salary.typical_error)}).`
            : "The model didn't beat this simple median in testing, so the estimate is the role median."}
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-4">
        <SalaryScale low={salary.low} high={salary.high} markers={markers} />
        {salary.level_median.status === "no_level" && (
          <p className="text-sm text-muted-foreground">Choose your level to compare with what postings at that level pay.</p>
        )}
        {salary.level_median.status === "too_few_salaries" && (
          <p className="text-sm text-muted-foreground">
            Too few posted salaries at this level ({salary.level_median.n}) to show a median.
          </p>
        )}
        <p className="text-xs text-muted-foreground">
          From salaries posted in job ads (mostly large U.S. metros), not offers or pay surveys. If the estimate and the
          median for your level differ a lot, trust the median: the model has few junior salaries to learn from.
        </p>
      </CardContent>
    </Card>
  );
}

function SkillsCard({ analysis }: { analysis: Analysis }) {
  const role = roleLabel(analysis.role);
  const have = analysis.core_skills.filter((s) => s.on_resume);
  const missing = analysis.core_skills.filter((s) => !s.on_resume);
  return (
    <Card>
      <CardHeader>
        <CardTitle>Skills</CardTitle>
        <CardDescription>
          Found on your resume, with how often {role} postings mention each one.
        </CardDescription>
      </CardHeader>
      <CardContent className="grid gap-6">
        <div className="grid gap-3">
          <div className="flex flex-wrap gap-2">
            {analysis.skills.length === 0 && (
              <p className="text-sm text-muted-foreground">
                No skills from our dictionary were found. If your resume is a scanned image, its text can&apos;t be read.
              </p>
            )}
            {analysis.skills.map((s) => (
              <Tooltip key={s.skill}>
                <TooltipTrigger render={<span />}>
                  <Badge
                    variant={s.share_of_role_postings >= 0.25 ? "default" : s.share_of_role_postings > 0 ? "secondary" : "outline"}
                    className="h-6 gap-1.5 px-2.5"
                  >
                    {s.skill}
                    <span className="tabular-nums opacity-75">{percent(s.share_of_role_postings)}</span>
                  </Badge>
                </TooltipTrigger>
                <TooltipContent>In {percent(s.share_of_role_postings)} of {role} postings</TooltipContent>
              </Tooltip>
            ))}
          </div>
          <div className="flex flex-wrap gap-4 text-xs text-muted-foreground">
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-primary" /> in 25%+ of postings</span>
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full bg-secondary ring-1 ring-primary/30" /> less often</span>
            <span className="flex items-center gap-1.5"><span className="size-2.5 rounded-full ring-1 ring-border" /> not asked for in this role</span>
          </div>
        </div>
        <div className="grid gap-6 border-t pt-5 md:grid-cols-2">
          <div className="grid content-start gap-2">
            <h3 className="flex items-center gap-2 text-sm font-medium">
              <CheckCircle2 className="size-4 text-success" aria-hidden />
              {role} core skills on your resume ({have.length})
            </h3>
            <ul className="grid gap-1.5">
              {have.map((s) => (
                <li key={s.skill} className="flex items-center gap-2 text-sm">
                  <span className="size-1.5 rounded-full bg-success" aria-label="on your resume" />
                  {s.skill}
                  <span className="ml-auto text-xs tabular-nums text-muted-foreground">{percent(s.share_of_role_postings)}</span>
                </li>
              ))}
              {have.length === 0 && <li className="text-sm text-muted-foreground">None yet.</li>}
            </ul>
          </div>
          <div className="grid content-start gap-2">
            <h3 className="flex items-center gap-2 text-sm font-medium text-muted-foreground">
              <Target className="size-4" aria-hidden />
              Not on your resume ({missing.length})
            </h3>
            <ul className="grid gap-1.5">
              {missing.slice(0, MISSING_SHOWN).map((s) => (
                <li key={s.skill} className="flex items-center gap-2 text-sm text-muted-foreground">
                  <span className="size-1.5 rounded-full bg-muted-foreground/40" aria-label="not on your resume" />
                  {s.skill}
                  <span className="ml-auto text-xs tabular-nums">{percent(s.share_of_role_postings)}</span>
                </li>
              ))}
              {missing.length > MISSING_SHOWN && (
                <li className="text-xs text-muted-foreground">+{missing.length - MISSING_SHOWN} more, each in fewer postings</li>
              )}
            </ul>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function SkillsToAdd({ analysis }: { analysis: Analysis }) {
  const role = roleLabel(analysis.role);
  return (
    <section className="grid gap-3" aria-labelledby="skills-to-add">
      <div className="flex items-start gap-3">
        <IconTile icon={ListChecks} tone="amber" />
        <div>
          <h2 id="skills-to-add" className="text-lg font-semibold tracking-tight">Top skills to add</h2>
          <p className="text-sm text-muted-foreground">
            The most in-demand {role} skills missing from your resume. Salary figures are associations in posted
            salaries, not promises: postings that ask for a skill can differ in other ways too.
          </p>
        </div>
      </div>
      {analysis.missing_skills.length === 0 ? (
        <p className="text-sm text-muted-foreground">Your resume covers every skill these postings ask for.</p>
      ) : (
        <div className="grid gap-4 md:grid-cols-3">
          {analysis.missing_skills.map((m, i) => (
            <Card key={m.skill}>
              <CardHeader className="gap-2">
                <div className="flex items-center justify-between">
                  <Badge variant="secondary" className="tabular-nums">#{i + 1}</Badge>
                  <span className="text-xs text-muted-foreground">in {percent(m.share_of_role_postings)} of postings</span>
                </div>
                <CardTitle className="text-lg">{m.skill}</CardTitle>
                <div className="h-1.5 overflow-hidden rounded-full bg-muted">
                  <div className="h-full rounded-full bg-chart-3" style={{ width: `${m.share_of_role_postings * 100}%` }} />
                </div>
              </CardHeader>
              <CardContent className="grid gap-3 text-sm">
                <div className="grid gap-0.5">
                  <div className="text-xs text-muted-foreground">Salary model what-if</div>
                  <div className="font-medium">{impactText(m.model_impact_status, m.model_impact)}</div>
                </div>
                <div className="grid gap-0.5">
                  <div className="text-xs text-muted-foreground">Median posted salary, with vs without it</div>
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
  );
}

function PostingsCard({ analysis }: { analysis: Analysis }) {
  const { postings } = analysis;
  return (
    <Card>
      <CardHeader>
        <CardTitle>Matching job postings</CardTitle>
        <CardDescription>
          {windowText(postings.window, postings.since)} Postings near your level come first, ranked by similarity of
          meaning — not just shared keywords.
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
                <TableHead className="hidden sm:table-cell">Level</TableHead>
                <TableHead className="hidden lg:table-cell">Shared skills</TableHead>
                <TableHead className="hidden w-28 sm:table-cell">Match</TableHead>
                <TableHead className="w-10"><span className="sr-only">Apply</span></TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {postings.items.map((p) => (
                <TableRow key={p.job_id}>
                  <TableCell className="whitespace-normal sm:max-w-72">
                    <div className="font-medium">{p.title}</div>
                    <div className="text-xs text-muted-foreground">
                      {[p.employer, p.location].filter(Boolean).join(" · ")}
                      {p.remote && " · Remote"}
                    </div>
                    {/* Phones: level and match under the title instead of in their own columns. */}
                    <div className="mt-1.5 flex items-center gap-2 sm:hidden">
                      <LevelBadge level={p.level} near={p.near_level} />
                      <span className="text-xs text-muted-foreground tabular-nums">{percent(p.similarity)} match</span>
                    </div>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <LevelBadge level={p.level} near={p.near_level} />
                  </TableCell>
                  <TableCell className="hidden max-w-80 whitespace-normal lg:table-cell">
                    <div className="flex flex-wrap gap-1">
                      {p.shared_skills.slice(0, 5).map((s) => (
                        <Badge key={s} variant="secondary" className="font-normal">{s}</Badge>
                      ))}
                      {p.shared_skills.length > 5 && (
                        <span className="self-center text-xs text-muted-foreground">+{p.shared_skills.length - 5}</span>
                      )}
                    </div>
                  </TableCell>
                  <TableCell className="hidden sm:table-cell">
                    <div className="flex items-center gap-2">
                      <div className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted">
                        <div className="h-full rounded-full bg-primary" style={{ width: `${p.similarity * 100}%` }} />
                      </div>
                      <span className="w-9 text-right text-xs tabular-nums">{percent(p.similarity)}</span>
                    </div>
                  </TableCell>
                  <TableCell>
                    {p.apply_link && (
                      <a
                        href={p.apply_link}
                        target="_blank"
                        rel="noopener noreferrer"
                        aria-label={`Open the posting: ${p.title}`}
                        className="inline-grid size-8 place-items-center rounded-md text-muted-foreground transition-colors hover:bg-muted hover:text-foreground"
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

function LevelBadge({ level, near }: { level: string | null | undefined; near: boolean }) {
  return (
    <Badge variant="outline" className={cn(near ? "border-success/40 bg-success/10 text-success" : "text-muted-foreground")}>
      {levelLabel(level)}
    </Badge>
  );
}
