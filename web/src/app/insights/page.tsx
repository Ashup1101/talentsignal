import type { Metadata } from "next";

import { InsightsView } from "@/components/insights-view";

export const metadata: Metadata = { title: "Job Insights" };

export default function Page() {
  return <InsightsView />;
}
