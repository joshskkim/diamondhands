'use client'

import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import Link from 'next/link'
import { useEffect, useRef, type CSSProperties } from 'react'
import { todayGamesQueryOptions } from '@/lib/api'
import { cn, parseApiDate } from '@/lib/utils'

/**
 * Projected-favorite glow. From the game's expected runs, picks the favorite side
 * and an intensity 0..1 that scales with the run margin (capped at ~2 R = a big
 * favorite). The favorite's abbreviation gets a colored glow whose brightness/spread
 * tracks how strongly we favor them; pick'ems stay neutral.
 */
const _GLOW_CAP_RUNS = 2.0

function favoriteGlow(
  home: number | null | undefined,
  away: number | null | undefined,
): { side: 'home' | 'away' | null; style: CSSProperties } {
  if (home == null || away == null) return { side: null, style: {} }
  const margin = Math.abs(home - away)
  if (margin < 0.05) return { side: null, style: {} } // effective pick'em
  const t = Math.min(margin / _GLOW_CAP_RUNS, 1) // 0..1 intensity
  const side = home > away ? 'home' : 'away'
  const style: CSSProperties = {
    color: `rgba(110, 231, 183, ${0.7 + 0.3 * t})`, // emerald, brighter when more favored
    textShadow: `0 0 ${5 + 11 * t}px rgba(52, 211, 153, ${0.35 + 0.5 * t})`,
  }
  return { side, style }
}

/**
 * Sticky, horizontally-scrolling strip of today's games. Lets you hop between
 * matchups without leaving the game view. Reads the already-cached today slate,
 * so switching games is an instant client navigation. The projected favorite in
 * each chip glows, more vividly the more we favor them.
 */
export function GameSelectorBar({ activeGameId }: { activeGameId?: number }) {
  const { data: games } = useQuery(todayGamesQueryOptions())
  const activeRef = useRef<HTMLAnchorElement | null>(null)

  // Bring the current game into view when the bar mounts / the slate loads.
  useEffect(() => {
    activeRef.current?.scrollIntoView({ inline: 'center', block: 'nearest' })
  }, [games, activeGameId])

  if (!games || games.length === 0) return null

  return (

    <div className="sticky top-0 z-30 -mx-4 mb-6 border-b border-white/10 bg-[#08090d]/90 px-4 py-2 backdrop-blur">
      <div className="flex gap-2 overflow-x-auto pb-1">
        {games.map((g) => {
          const active = g.gameId === activeGameId
          const total = g.projection?.expectedTotal
          const glow = favoriteGlow(
            g.projection?.expectedHomeRuns,
            g.projection?.expectedAwayRuns,
          )
          return (
            <Link
              key={g.gameId}
              ref={active ? activeRef : undefined}
              href={`/games/${g.gameId}`}
              className={cn(
                'shrink-0 rounded-lg border px-3 py-1.5 transition-colors',
                active
                  ? 'border-cyan-400/30 bg-cyan-400/10 text-cyan-300'
                  : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-zinc-100',
              )}
            >
              <div className="flex items-center gap-2 text-sm font-semibold tracking-tight whitespace-nowrap">
                <span style={glow.side === 'away' ? glow.style : undefined}>{g.away.abbr}</span>
                <span className="font-normal text-zinc-600">@</span>
                <span style={glow.side === 'home' ? glow.style : undefined}>{g.home.abbr}</span>
              </div>
              <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-zinc-500 whitespace-nowrap">
                <span className="font-mono tabular-nums">
                  {format(parseApiDate(g.startTimeUtc), 'h:mm a')}
                </span>
                {total != null && (
                  <>
                    <span className="text-zinc-700">·</span>
                    <span className="font-mono tabular-nums">{total.toFixed(1)} R</span>
                  </>
                )}
              </div>
            </Link>
          )
        })}
      </div>
    </div>
  )
}
