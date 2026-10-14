"use client";

import { FileText, Loader2, Lock, Sparkles, UploadCloud, X } from "lucide-react";
import { useRef, useState } from "react";

import { AnalysisResults } from "@/components/analysis/analysis-results";
import { LabeledSelect } from "@/components/labeled-select";
import { PageIntro } from "@/components/page-intro";
import { ErrorAlert, LoadingBlock } from "@/components/states";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
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
      <PageIntro title="Resume Analyzer">
        Compare your resume with what real postings ask for: skills, match by role, an estimated salary, the skills
        worth adding, and matching postings from this week.
      </PageIntro>

      {options.error && <ErrorAlert error={options.error} />}

      <Card>
        <CardContent className="grid gap-6">
          <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
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
            <div className="grid gap-1.5">
              <Label htmlFor="remote">Remote work</Label>
              <div className="flex h-8 items-center gap-2">
                <Switch id="remote" checked={choice.remote} onCheckedChange={(v) => update({ remote: v })} />
                <span className="text-sm text-muted-foreground">{choice.remote ? "Yes" : "No"}</span>
              </div>
            </div>
          </div>

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
              "flex flex-col items-center gap-3 rounded-xl border-2 border-dashed p-8 text-center transition-colors",
              dragging ? "border-primary bg-primary/5" : "border-muted-foreground/25",
            )}
          >
            {file ? (
              <div className="flex items-center gap-2 text-sm">
                <FileText className="size-5 text-primary" aria-hidden />
                <span className="font-medium">{file.name}</span>
                <span className="text-muted-foreground">({Math.max(1, Math.round(file.size / 1024))} KB)</span>
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
                <UploadCloud className="size-8 text-muted-foreground" aria-hidden />
                <p className="text-sm text-muted-foreground">
                  Drag a PDF here, or choose a file (text-based PDF, up to {options.data?.max_upload_mb ?? 5} MB)
                </p>
              </>
            )}
            <div className="flex flex-wrap justify-center gap-2">
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
          <p className="flex items-center gap-1.5 text-xs text-muted-foreground">
            <Lock className="size-3.5" aria-hidden /> Your resume is analyzed in memory and never stored, logged or
            shared.
          </p>
        </CardContent>
      </Card>

      {busy && (
        <div className="flex items-center gap-2 text-sm text-muted-foreground" role="status">
          <Loader2 className="size-4 animate-spin" aria-hidden /> Comparing your resume with real postings…
        </div>
      )}
      {error && <ErrorAlert error={error} title="Couldn't analyze this resume" />}
      {busy && !result && <LoadingBlock rows={3} />}
      {result && <AnalysisResults analysis={result} sample={file?.name === "sample-resume.pdf"} />}
    </div>
  );
}
