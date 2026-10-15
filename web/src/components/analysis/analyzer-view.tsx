"use client";

import { BadgeDollarSign, FileSearch, FileText, ListChecks, Loader2, Lock, Sparkles, Target, UploadCloud, Users, X } from "lucide-react";
import { useRef, useState } from "react";

import { AnalysisResults } from "@/components/analysis/analysis-results";
import { IconTile, type Tone } from "@/components/icon-tile";
import { LabeledSelect } from "@/components/labeled-select";
import { PageIntro } from "@/components/page-intro";
import { ErrorAlert, LoadingBlock } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import { type Analysis, type AnalyzeParams, api, ApiError } from "@/lib/api";
import { roleLabel } from "@/lib/format";
import { useApi } from "@/lib/use-api";
import { cn } from "@/lib/utils";

export const SAMPLE_RESUME_URL = "/sample-resume.pdf";

export function AnalyzerView() {
  const options = useApi(() => api.options(), []);
  const [choice, setChoice] = useState<Omit<AnalyzeParams, "role"> & { role: string | null }>({
    role: null,
    level: "unknown",
    state: null,
    remote: false,
  });
  const [file, setFile] = useState<File | null>(null);
  const [result, setResult] = useState<Analysis | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const roles = options.data?.roles ?? [];
  const chosenRole = choice.role ?? (roles.includes("data engineer") ? "data engineer" : roles[0] ?? null);
  const maxBytes = (options.data?.max_upload_mb ?? 5) * 1024 * 1024;

  async function analyze(pdf: File, params: typeof choice) {
    const role = params.role ?? chosenRole;
    if (!role) return;
    setBusy(true);
    setError(null);
    try {
      setResult(await api.analyze(pdf, { ...params, role }));
    } catch (e) {
      setResult(null);
      setError(e instanceof ApiError ? e : new ApiError(0, "Something went wrong.", "error"));
    } finally {
      setBusy(false);
    }
  }

  // Changing the role, level, state or remote re-runs the analysis on the same file.
  function update(patch: Partial<typeof choice>) {
    const next = { ...choice, ...patch };
    setChoice(next);
    if (file && result) void analyze(file, next);
  }

  function choose(candidate: File | undefined) {
    if (!candidate) return;
    if (candidate.type !== "application/pdf" && !candidate.name.toLowerCase().endsWith(".pdf")) {
      setError(new ApiError(415, "Please choose a PDF file.", "not_pdf"));
      return;
    }
    if (candidate.size > maxBytes) {
      setError(new ApiError(413, `The file is larger than ${options.data?.max_upload_mb ?? 5} MB.`, "too_large"));
      return;
    }
    setFile(candidate);
    void analyze(candidate, choice);
  }

  async function loadSample() {
    const response = await fetch(SAMPLE_RESUME_URL);
    choose(new File([await response.blob()], "sample-resume.pdf", { type: "application/pdf" }));
  }

  return (
    <div className="grid gap-8">
      <PageIntro title="Resume Analyzer" icon={FileSearch}>
        Compare your resume with what real postings ask for: skills, match by role, an estimated salary, the skills
        worth adding, and matching postings from this week.
      </PageIntro>

      {options.error && <ErrorAlert error={options.error} />}

      <div className="grid items-start gap-6 lg:grid-cols-[22rem_1fr]">
        <Card className="lg:sticky lg:top-20">
          <CardHeader>
            <CardTitle>Your resume</CardTitle>
            <CardDescription>Pick the role you&apos;re aiming for, then add a PDF.</CardDescription>
          </CardHeader>
          <CardContent className="grid gap-5">
            <div
              onDragOver={(e) => {
                e.preventDefault();
                setDragging(true);
              }}
              onDragLeave={() => setDragging(false)}
              onDrop={(e) => {
                e.preventDefault();
                setDragging(false);
                choose(e.dataTransfer.files[0]);
              }}
              className={cn(
                "flex flex-col items-center gap-3 rounded-xl border-2 border-dashed p-6 text-center transition-colors",
                dragging ? "border-primary bg-primary/5" : "border-border bg-muted/40",
              )}
            >
              {file ? (
                <div className="flex w-full items-center gap-2 rounded-lg bg-card p-2 text-left text-sm ring-1 ring-border">
                  <FileText className="size-5 shrink-0 text-primary" aria-hidden />
                  <span className="min-w-0 flex-1 truncate font-medium">{file.name}</span>
                  <span className="shrink-0 text-xs text-muted-foreground">{Math.max(1, Math.round(file.size / 1024))} KB</span>
                  <Button
                    variant="ghost"
                    size="icon-xs"
                    aria-label="Remove file"
                    onClick={() => {
                      setFile(null);
                      setResult(null);
                      setError(null);
                    }}
                  >
                    <X aria-hidden />
                  </Button>
                </div>
              ) : (
                <>
                  <span className="grid size-11 place-items-center rounded-full bg-primary/10 text-primary">
                    <UploadCloud className="size-5" aria-hidden />
                  </span>
                  <p className="text-sm text-muted-foreground">
                    Drag a PDF here
                    <br />
                    <span className="text-xs">Text-based PDF, up to {options.data?.max_upload_mb ?? 5} MB</span>
                  </p>
                </>
              )}
              <div className="grid w-full gap-2">
                <Button onClick={() => input.current?.click()} disabled={busy || !chosenRole}>
                  {file ? "Choose another file" : "Choose a PDF"}
                </Button>
                <Button variant="outline" onClick={() => void loadSample()} disabled={busy || !chosenRole}>
                  <Sparkles aria-hidden /> Try a sample resume
                </Button>
              </div>
              <input
                ref={input}
                type="file"
                accept="application/pdf,.pdf"
                className="sr-only"
                aria-label="Resume PDF"
                onChange={(e) => {
                  choose(e.target.files?.[0]);
                  e.target.value = "";
                }}
              />
            </div>

            <div className="grid gap-4">
              <LabeledSelect
                id="role"
                label="Target role"
                value={chosenRole}
                options={roles.map((r) => ({ value: r, label: roleLabel(r) }))}
                onChange={(v) => v && update({ role: v })}
              />
              <LabeledSelect
                id="level"
                label="Your level"
                value={choice.level}
                options={(options.data?.levels ?? []).map((l) => ({ value: l.value, label: l.label }))}
                onChange={(v) => update({ level: v ?? "unknown" })}
              />
              <LabeledSelect
                id="state"
                label="State"
                value={choice.state ?? null}
                noneLabel="Other / not listed"
                options={(options.data?.states ?? []).map((s) => ({ value: s, label: s }))}
                onChange={(v) => update({ state: v })}
              />
              <div className="flex items-center justify-between rounded-lg border px-3 py-2">
                <Label htmlFor="remote">Looking for remote work</Label>
                <Switch id="remote" checked={choice.remote} onCheckedChange={(v) => update({ remote: v })} />
              </div>
            </div>

            <p className="flex items-start gap-1.5 text-xs text-muted-foreground">
              <Lock className="mt-0.5 size-3.5 shrink-0" aria-hidden /> Analyzed in memory and never stored, logged or
              shared.
            </p>
          </CardContent>
        </Card>

        <div className="grid min-w-0 gap-6">
          {busy && (
            <div className="flex items-center gap-2 rounded-lg bg-secondary px-3 py-2 text-sm text-secondary-foreground" role="status">
              <Loader2 className="size-4 animate-spin" aria-hidden /> Comparing your resume with real postings…
            </div>
          )}
          {error && <ErrorAlert error={error} title="Couldn't analyze this resume" />}
          {busy && !result && <LoadingBlock rows={4} />}
          {result && <AnalysisResults analysis={result} sample={file?.name === "sample-resume.pdf"} />}
          {!result && !busy && <WhatYouGet />}
        </div>
      </div>
    </div>
  );
}

const PREVIEW = [
  { icon: Target, tone: "indigo", title: "Match by role", text: "How much of each role's core skill set your resume covers, weighted by demand." },
  { icon: BadgeDollarSign, tone: "teal", title: "Salary estimate", text: "A model estimate with its error range, next to what postings at your level pay." },
  { icon: ListChecks, tone: "amber", title: "Skills to add", text: "The most in-demand skills you're missing, with how they relate to posted salaries." },
  { icon: Users, tone: "rose", title: "Matching postings", text: "This week's postings closest to your resume in meaning, near your level first." },
] satisfies { icon: typeof Target; tone: Tone; title: string; text: string }[];

function WhatYouGet() {
  return (
    <Card className="bg-hero-glow">
      <CardHeader>
        <CardTitle>What you&apos;ll get</CardTitle>
        <CardDescription>Add a resume (or try the sample) and the analysis appears here.</CardDescription>
      </CardHeader>
      <CardContent className="grid gap-5 sm:grid-cols-2">
        {PREVIEW.map(({ icon, tone, title, text }) => (
          <div key={title} className="flex gap-3">
            <IconTile icon={icon} tone={tone} />
            <div className="grid gap-1">
              <div className="font-medium">{title}</div>
              <p className="text-sm text-muted-foreground">{text}</p>
            </div>
          </div>
        ))}
      </CardContent>
    </Card>
  );
}
