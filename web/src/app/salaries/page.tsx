import type { Metadata } from "next";

import { SalariesView } from "@/components/salaries-view";

export const metadata: Metadata = { title: "Salary Explorer" };

export default function Page() {
  return <SalariesView />;
}
