'use client'

import { useQuery } from '@tanstack/react-query'
import { todayGamesQueryOptions } from '@/lib/api'
import { cn } from '@/lib/utils'

/**
 * A small "X/N projected" chip showing how many of today's games we've already
 * projected lines for. Projections roll in through the day as lineups post (the
 * afternoon re-projection loop), so this tracker climbs toward the full slate.
 *
 * A game counts as projected once it has a game-level projection (TodayGame.projection
 * is non-null only when a game_projections row exists). Reuses the home page's
 * today-games query — TanStack Query dedupes by key, so this adds no extra fetch.
 * Renders nothing while loading or when the slate is empty.
 */
export function ProjectedBadge({ className }: { className?: string }) {
  const { data: games } = useQuery(todayGamesQueryOptions())
  if (!games || games.length === 0) return null

  const projected = games.filter((g) => g.projection != null).length
  const complete = projected === games.length

  return (
    <span
      title={`${projected} of ${games.length} games projected so far — lines fill in as lineups post`}
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
        complete ? 'bg-emerald-400/15 text-emerald-300' : 'bg-amber-400/15 text-amber-300',
        className,
      )}
    >
      <span className="font-mono tabular-nums">
        {projected}/{games.length}
      </span>{' '}
      projected
    </span>
  )
}
