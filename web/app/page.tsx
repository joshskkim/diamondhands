'use client'

import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ModelPicks } from '@/components/home/model-picks'
import { RecentResults } from '@/components/home/recent-results'
import { PropBoard } from '@/components/home/prop-board'
import { SimBoards } from '@/components/home/sim-boards'
import { SlateProjectionsChart } from '@/components/home/slate-projections-chart'
import { GameSelectorBar } from '@/components/game/game-selector-bar'
import { GamesBadge } from '@/components/games-badge'
import { ProjectedBadge } from '@/components/projected-badge'
import { QueryError } from '@/components/ui/query-states'
import { useLiveStream } from '@/components/home/use-live-stream'
import { todayGamesQueryOptions } from '@/lib/api'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-white/5 rounded ${className}`} />
}

export default function SlatePage() {
  const today = format(new Date(), 'EEEE, MMMM d, yyyy')
  const { data: games = [], isPending, isError, refetch } = useQuery(todayGamesQueryOptions())
  // Open one SSE connection while any game is in progress; patches live state into the
  // todayGames cache that every board below reads.
  useLiveStream(games)

  return (
    <main className="max-w-6xl mx-auto w-full px-4 py-8">
      {/* quick game switcher */}
      <GameSelectorBar />

      {/* page header */}
      <div className="mb-8">
        <div className={microLabel}>Today&apos;s Board</div>
        <h1 className="text-3xl font-bold tracking-tight text-zinc-100 mt-1">MLB Projections</h1>
        <p className="text-zinc-500 text-sm mt-1 flex items-center gap-2">
          <span>{today}</span>
          <GamesBadge />
          <ProjectedBadge />
        </p>
      </div>

      {isError && (
        <QueryError message="Couldn’t load today’s slate. The API may be unreachable." onRetry={refetch} />
      )}

      {!isError && (
        <>
          {/* the model's curated 1–3 lines (or an honest pass) */}
          <ModelPicks />

          {/* yesterday's picks, graded ✓/✗ — the running track record */}
          <RecentResults />

          {/* odds-independent: the most likely batter per prop market, with reasons */}
          <PropBoard />

          {/* condensed game-sim leans (formerly the Most Likely page) */}
          <SimBoards />

          <section>
            <h2 className="text-sm font-semibold tracking-tight text-zinc-100 mb-1">
              Projected Favorites
            </h2>
            <p className="text-zinc-500 text-xs mb-3">
              Today&apos;s games ranked by our projected favorite&apos;s run margin (the game bar
              above is the full slate).
            </p>
            {isPending ? (
              <div className="space-y-1.5">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-8 w-full rounded-lg" />
                ))}
              </div>
            ) : games.length === 0 ? (
              <p className="text-zinc-500 text-sm">No games scheduled today.</p>
            ) : (
              <SlateProjectionsChart games={games} />
            )}
          </section>
        </>
      )}
    </main>
  )
}
