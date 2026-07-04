'use client'

import { useEffect, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { todayGamesQueryOptions } from '@/lib/api'
import { cn } from '@/lib/utils'

/**
 * When the server next re-projects the slate, as a local-time Date.
 *
 * The projector runs on a fixed ET cron (keep in sync with deploy/crontab.example):
 *   • 09:00 ET — morning full run (builds the slate)
 *   • every :00 / :30 ET, 12:00–23:30 — afternoon/evening re-projection as lineups post
 *
 * We read the current ET wall clock via Intl (DST-safe, no library), find the next tick in
 * ET minutes-of-day, then add that delta to `now` — so the returned Date renders correctly
 * in the viewer's own timezone. Returns null only if the time parse fails.
 */
function nextProjectionRefresh(now: Date): Date | null {
  const parts = new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour12: false,
    hour: '2-digit',
    minute: '2-digit',
  }).formatToParts(now)
  const hour = Number(parts.find((p) => p.type === 'hour')?.value)
  const minute = Number(parts.find((p) => p.type === 'minute')?.value)
  if (Number.isNaN(hour) || Number.isNaN(minute)) return null
  // Intl can render midnight ET as hour 24; normalize to 0.
  const etMinutes = (hour % 24) * 60 + minute

  // Next scheduled tick, in ET minutes-of-day (may roll past 24h → tomorrow's 09:00).
  let targetMinutes: number
  if (etMinutes < 9 * 60) {
    targetMinutes = 9 * 60 // before the morning run
  } else if (etMinutes < 12 * 60) {
    targetMinutes = 12 * 60 // morning run done, afternoon loop not yet started
  } else if (etMinutes < 23 * 60 + 30) {
    targetMinutes = (Math.floor(etMinutes / 30) + 1) * 30 // next :00 / :30 in the loop
  } else {
    targetMinutes = 24 * 60 + 9 * 60 // after the last tick → tomorrow 09:00
  }

  const deltaMs = (targetMinutes - etMinutes) * 60_000
  return new Date(now.getTime() + deltaMs)
}

/**
 * A small "X/N projected" chip showing how many of today's games we've already
 * projected lines for, plus when the next server re-projection lands. Projections roll
 * in through the day as lineups post (the afternoon re-projection loop), so this tracker
 * climbs toward the full slate and the today-games query polls to pick up each tick.
 *
 * A game counts as projected once it has a game-level projection (TodayGame.projection
 * is non-null only when a game_projections row exists). Reuses the home page's
 * today-games query — TanStack Query dedupes by key, so this adds no extra fetch.
 * Renders nothing while loading or when the slate is empty.
 */
export function ProjectedBadge({ className }: { className?: string }) {
  const { data: games } = useQuery(todayGamesQueryOptions())

  // Re-render every 30s so the "refreshes ~h:mm" label rolls over to the next tick.
  const [refreshAt, setRefreshAt] = useState<Date | null>(() => nextProjectionRefresh(new Date()))
  useEffect(() => {
    const tick = () => setRefreshAt(nextProjectionRefresh(new Date()))
    tick()
    const id = setInterval(tick, 30_000)
    return () => clearInterval(id)
  }, [])

  if (!games || games.length === 0) return null

  const projected = games.filter((g) => g.projection != null).length
  const complete = projected === games.length

  return (
    <span className={cn('inline-flex shrink-0 items-center gap-2', className)}>
      <span
        title={`${projected} of ${games.length} games projected so far — lines fill in as lineups post`}
        className={cn(
          'inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
          complete ? 'bg-emerald-400/15 text-emerald-300' : 'bg-amber-400/15 text-amber-300',
        )}
      >
        <span className="font-mono tabular-nums">
          {projected}/{games.length}
        </span>{' '}
        projected
      </span>
      {!complete && refreshAt && (
        <span className="text-[10px] text-zinc-500" title="Next server re-projection">
          refreshes ~{format(refreshAt, 'h:mm a')}
        </span>
      )}
    </span>
  )
}
