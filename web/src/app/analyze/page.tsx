import type { Metadata } from "next";

import { AnalyzerView } from "@/components/analysis/analyzer-view";

export const metadata: Metadata = { title: "Resume Analyzer" };

export default function AnalyzePage() {
  return <AnalyzerView />;
}
