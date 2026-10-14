import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";

import "./globals.css";

import { SiteHeader } from "@/components/site-header";
import { TooltipProvider } from "@/components/ui/tooltip";

const geistSans = Geist({ variable: "--font-geist-sans", subsets: ["latin"] });
const geistMono = Geist_Mono({ variable: "--font-geist-mono", subsets: ["latin"] });

export const metadata: Metadata = {
  title: { default: "TalentSignal — your resume vs real job postings", template: "%s · TalentSignal" },
  description:
    "Upload a resume and see the skills it shows, how well it matches data and software roles, an estimated salary, the in-demand skills it's missing, and matching postings from this week.",
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} h-full antialiased`}>
      <body className="flex min-h-full flex-col bg-background">
        <TooltipProvider>
          <SiteHeader />
          <main className="mx-auto w-full max-w-6xl flex-1 px-4 py-8">{children}</main>
          <footer className="border-t">
            <div className="mx-auto flex w-full max-w-6xl flex-col gap-1 px-4 py-6 text-xs text-muted-foreground sm:flex-row sm:justify-between">
              <span>Job postings from JSearch, collected nightly · salary benchmarks from the U.S. BLS.</span>
              <span>Resumes are analyzed in memory and never stored.</span>
            </div>
          </footer>
        </TooltipProvider>
      </body>
    </html>
  );
}
