'use client'

import { useQuery } from '@tanstack/react-query'
import { todayGamesQueryOptions } from '@/lib/api'
import { cn } from '@/lib/utils'

/**
 * A small "N games" chip showing how many MLB games are loaded for today. Reuses
 * the home page's today-games query (TanStack Query dedupes by key, so this adds
 * no extra fetch). Renders nothing while loading or when the slate is empty.
 */
export function GamesBadge({ className }: { className?: string }) {
  const { data: games } = useQuery(todayGamesQueryOptions())
  if (!games || games.length === 0) return null
  return (
    <span
      title={`${games.length} MLB games loaded for today`}
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded bg-cyan-400/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-cyan-300',
        className,
      )}
    >
      <span className="font-mono tabular-nums">{games.length}</span> games
    </span>
  )
}
