'use client'

import { format } from 'date-fns'
import { GameCard } from '@/components/home/game-card'
import { BatterBoards, GameBoards } from '@/components/home/pick-boards'
import { usePicks } from '@/components/home/use-picks'
import { QueryError } from '@/components/ui/query-states'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={`animate-pulse bg-white/5 rounded ${className}`} />
}

function BoardSkeleton() {
  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl p-4 space-y-3">
      <Skeleton className="h-4 w-40" />
      <Skeleton className="h-3 w-56" />
      {Array.from({ length: 5 }).map((_, i) => (
        <Skeleton key={i} className="h-7 w-full" />
      ))}
    </div>
  )
}

export default function SlatePage() {
  const today = format(new Date(), 'EEEE, MMMM d, yyyy')
  const { games, picks, isPending, isError, projectionsLoading, refetch } = usePicks()

  const projectedGames = games.filter((g) => g.projection)
  const showBoards = picks.length > 0 || projectedGames.length > 0

  return (
    <main className="max-w-6xl mx-auto w-full px-4 py-8">
      {/* page header */}
      <div className="mb-8">
        <div className={microLabel}>Today&apos;s Board</div>
        <h1 className="text-3xl font-bold tracking-tight text-zinc-100 mt-1">
          MLB Projections
        </h1>
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
        <QueryError message="Couldn’t load today’s slate. The API may be unreachable." onRetry={refetch} />
      )}

      {!isError && (
        <>
          {/* ── Top picks ─────────────────────────────────────────────── */}
          <section className="mb-10">
            <div className="flex items-baseline justify-between mb-3">
              <h2 className="text-sm font-semibold tracking-tight text-zinc-100">
                Top Picks &amp; Edges
              </h2>
              {projectionsLoading && (
                <span className="text-[11px] text-zinc-500">Loading projections…</span>
              )}
            </div>

            {isPending || (projectionsLoading && picks.length === 0) ? (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                {Array.from({ length: 6 }).map((_, i) => (
                  <BoardSkeleton key={i} />
                ))}
              </div>
            ) : showBoards ? (
              <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-4">
                <BatterBoards picks={picks} />
                <GameBoards games={games} />
              </div>
            ) : (
              <p className="text-zinc-500 text-sm bg-[#0e1015] border border-white/10 rounded-xl p-6">
                No projections yet — probable pitchers or lineups aren&apos;t confirmed for
                today&apos;s games.
              </p>
            )}
          </section>

          {/* ── Full slate ────────────────────────────────────────────── */}
          <section>
            <h2 className="text-sm font-semibold tracking-tight text-zinc-100 mb-3">
              Full Slate
            </h2>
            {isPending ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {Array.from({ length: 6 }).map((_, i) => (
                  <Skeleton key={i} className="h-44 w-full rounded-xl" />
                ))}
              </div>
            ) : games.length === 0 ? (
              <p className="text-zinc-500 text-sm">No games scheduled today.</p>
            ) : (
              <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
                {games.map((game) => (
                  <GameCard key={game.gameId} game={game} />
                ))}
              </div>
            )}
          </section>
        </>
      )}
    </main>
  )
}
