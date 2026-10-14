import type { Metadata } from "next";

import { SkillsView } from "@/components/skills-view";

export const metadata: Metadata = { title: "Skill Demand" };

export default function Page() {
  return <SkillsView />;
}
