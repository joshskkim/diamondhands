'use client'

import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ModelPicks } from '@/components/home/model-picks'
import { PropBoard } from '@/components/home/prop-board'
import { SimBoards } from '@/components/home/sim-boards'
import { SlateProjectionsChart } from '@/components/home/slate-projections-chart'
import { GameSelectorBar } from '@/components/game/game-selector-bar'
import { todayGamesQueryOptions } from '@/lib/api'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-white/5 rounded ${className}`} />
}

export default function SlatePage() {
  const today = format(new Date(), 'EEEE, MMMM d, yyyy')
  const { data: games = [], isPending, isError } = useQuery(todayGamesQueryOptions())

  return (
    <main className="max-w-6xl mx-auto w-full px-4 py-8">
      {/* quick game switcher */}
      <GameSelectorBar />

      {/* page header */}
      <div className="mb-8">
        <div className={microLabel}>Today&apos;s Board</div>
        <h1 className="text-3xl font-bold tracking-tight text-zinc-100 mt-1">MLB Projections</h1>
        <p className="text-zinc-500 text-sm mt-1">
          {today}
          {games.length > 0 && (
            <>
              {' · '}
              <span className="font-mono tabular-nums">{games.length}</span> games
            </>
          )}
        </p>
      </div>

      {isError && (
        <div className="text-rose-400 text-sm bg-rose-400/10 border border-rose-400/30 rounded-xl p-4">
          Failed to load today&apos;s slate. Is the API running?
        </div>
      )}

      {!isError && (
        <>
          {/* the model's curated 1–3 lines (or an honest pass) */}
          <ModelPicks />

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
