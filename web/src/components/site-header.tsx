"use client";

import { BarChart3, FileSearch, LineChart, Network, Radar } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export const NAV = [
  { href: "/analyze/", label: "Resume Analyzer", icon: FileSearch },
  { href: "/salaries/", label: "Salaries", icon: BarChart3 },
  { href: "/skills/", label: "Skill Demand", icon: LineChart },
  { href: "/insights/", label: "Job Insights", icon: Network },
] as const;

export function SiteHeader() {
  const pathname = usePathname() ?? "/";
  return (
    <header className="sticky top-0 z-40 border-b bg-background/80 backdrop-blur-md">
      <div className="mx-auto flex h-16 w-full max-w-6xl items-center gap-4 px-4">
        <Link href="/" className="flex items-center gap-2.5 font-semibold tracking-tight">
          <span className="grid size-8 place-items-center rounded-lg bg-primary text-primary-foreground shadow-sm">
            <Radar className="size-[18px]" aria-hidden />
          </span>
          <span className="hidden sm:inline">TalentSignal</span>
        </Link>
        <nav aria-label="Main" className="flex flex-1 items-center gap-1 overflow-x-auto text-sm">
          {NAV.map(({ href, label, icon: Icon }) => {
            const active = pathname.startsWith(href.replace(/\/$/, ""));
            return (
              <Link
                key={href}
                href={href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex shrink-0 items-center gap-1.5 rounded-full px-3 py-1.5 text-muted-foreground transition-colors hover:bg-muted hover:text-foreground",
                  active && "bg-secondary font-medium text-secondary-foreground hover:bg-secondary",
                )}
              >
                <Icon className="size-4" aria-hidden />
                <span className="hidden md:inline">{label}</span>
              </Link>
            );
          })}
        </nav>
        {!pathname.startsWith("/analyze") && (
          <Link href="/analyze/" className={cn(buttonVariants({ size: "sm" }), "hidden sm:inline-flex")}>
            Analyze resume
          </Link>
        )}
      </div>
    </header>
  );
}
