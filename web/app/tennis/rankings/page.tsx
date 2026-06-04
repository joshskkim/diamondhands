import type { Metadata } from "next";
import { Trophy } from "lucide-react";
import { ComingSoon } from "../_components/coming-soon";

export const metadata: Metadata = { title: "Tennis Rankings" };

export default function TennisRankingsPage() {
  return (
    <main className="max-w-3xl mx-auto w-full px-4 py-8">
      <ComingSoon
        label="Tennis · Rankings"
        icon={Trophy}
        title="Player rankings"
        description="Player rankings & form — coming soon."
      />
    </main>
  );
}
