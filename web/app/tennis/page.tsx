import type { Metadata } from "next";
import Link from "next/link";
import { Trophy } from "lucide-react";
import { ComingSoon } from "./_components/coming-soon";

export const metadata: Metadata = { title: "Tennis" };

const tabs = [
  { href: "/tennis/matches", label: "Matches" },
  { href: "/tennis/rankings", label: "Rankings" },
];

export default function TennisPage() {
  return (
    <main className="max-w-6xl mx-auto w-full px-4 py-8">
      <p className="text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium">
        Coming soon
      </p>
      <h1 className="mt-1 text-3xl text-zinc-100">Tennis</h1>
      <p className="mt-2 max-w-xl text-sm text-zinc-400">
        Tennis projections and best bets are on the way. We&apos;re building
        match-level model edges and player form so you can find value across the
        tour.
      </p>

      <nav className="mt-5 flex flex-wrap gap-2">
        {tabs.map((tab) => (
          <Link
            key={tab.href}
            href={tab.href}
            className="rounded-lg border border-white/10 bg-[#0e1015] px-3 py-1.5 text-sm text-zinc-300 transition-colors hover:border-cyan-400/40 hover:text-cyan-400"
          >
            {tab.label}
          </Link>
        ))}
      </nav>

      <div className="mt-8">
        <ComingSoon
          icon={Trophy}
          title="Tennis is coming soon"
          description="Projections, match edges, and rankings are in the works. Check back shortly."
        />
      </div>
    </main>
  );
}
