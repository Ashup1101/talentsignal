"use client";

import { BarChart3, FileSearch, LineChart, Network, Radar } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { cn } from "@/lib/utils";

export const NAV = [
  { href: "/analyze/", label: "Resume Analyzer", icon: FileSearch },
  { href: "/salaries/", label: "Salaries", icon: BarChart3 },
  { href: "/skills/", label: "Skill Demand", icon: LineChart },
  { href: "/insights/", label: "Job Insights", icon: Network },
] as const;

export function SiteHeader() {
  const pathname = usePathname();
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur supports-[backdrop-filter]:bg-background/60">
      <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-6 px-4">
        <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight">
          <Radar className="size-5 text-primary" aria-hidden />
          TalentSignal
        </Link>
        <nav aria-label="Main" className="flex flex-1 items-center gap-1 overflow-x-auto text-sm">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname?.startsWith(href.replace(/\/$/, ""));
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 rounded-md px-2.5 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                  active && "bg-muted font-medium text-foreground",
                )}
              >
                <Icon className="size-4" aria-hidden />
                <span className="hidden sm:inline">{label}</span>
              </Link>
            );
          })}
        </nav>
      </div>
    </header>
  );
}
