import type { Metadata } from 'next'
import Link from 'next/link'
import { Target } from 'lucide-react'
import { cn } from '@/lib/utils'

export const metadata: Metadata = { title: 'Leaderboard' }

const microLabel =
  'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

const cardBase = 'bg-[#0e1015] border border-white/10 rounded-xl p-5'

export default function LeaderboardPage() {
  return (
    <main className="max-w-6xl mx-auto w-full px-4 py-8">
      {/* page header */}
      <div className="mb-8">
        <div className={microLabel}>Hub</div>
        <h1 className="text-3xl font-bold tracking-tight text-zinc-100 mt-1">
          Leaderboards
        </h1>
        <p className="text-zinc-500 text-sm mt-1">
          Jump into the day&apos;s sharpest edges, ranked across sports.
        </p>
      </div>

      <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
        {/* MLB — Pitch Matchups */}
        <Link
          href="/mlb/leaderboards/pitch-types"
          className={cn(
            cardBase,
            'group flex flex-col gap-3 transition-colors hover:border-cyan-400/40',
          )}
        >
          <div className="flex items-center justify-between">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-cyan-400/10 text-cyan-400">
              <Target className="h-5 w-5" aria-hidden="true" />
            </div>
            <span className={microLabel}>MLB</span>
          </div>
          <div>
            <h2 className="text-base font-semibold tracking-tight text-zinc-100 group-hover:text-cyan-400">
              Pitch Matchups
            </h2>
            <p className="text-zinc-500 text-sm mt-1">
              Today&apos;s hitters with the biggest edge vs a pitch their opposing
              starter throws often.
            </p>
          </div>
        </Link>

        {/* Tennis — coming soon */}
        <div
          className={cn(cardBase, 'flex flex-col gap-3 opacity-60')}
          aria-disabled="true"
        >
          <div className="flex items-center justify-between">
            <div className="flex h-10 w-10 items-center justify-center rounded-lg bg-white/5 text-zinc-500">
              <Target className="h-5 w-5" aria-hidden="true" />
            </div>
            <span className="text-[10px] uppercase tracking-[0.12em] font-medium rounded-full border border-white/10 px-2 py-0.5 text-zinc-500">
              Coming soon
            </span>
          </div>
          <div>
            <h2 className="text-base font-semibold tracking-tight text-zinc-400">
              Tennis
            </h2>
            <p className="text-zinc-600 text-sm mt-1">
              Player-vs-surface and serve edges. Not yet available.
            </p>
          </div>
        </div>
      </div>
    </main>
  )
}
