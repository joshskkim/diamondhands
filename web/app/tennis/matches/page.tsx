import type { Metadata } from "next";
import { Calendar } from "lucide-react";
import { ComingSoon } from "../_components/coming-soon";

export const metadata: Metadata = { title: "Tennis Matches" };

export default function TennisMatchesPage() {
  return (
    <main className="max-w-3xl mx-auto w-full px-4 py-8">
      <ComingSoon
        label="Tennis · Matches"
        icon={Calendar}
        title="Match projections"
        description="Match projections & model edges — coming soon."
      />
    </main>
  );
}
