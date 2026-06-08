'use client'

import Link from 'next/link'
import type { TodayGame } from '@/lib/types'

/**
 * Ranked "most likely projections" chart for the slate: each game as a horizontal
 * bar of the projected favorite's run margin, sorted strongest-first. Replaces the
 * redundant full-slate grid (the game-selector bar already lists every matchup).
 * The favorite glows brighter the more we favor them (matches the game bar).
 */
const GLOW_CAP_RUNS = 2.0

type Row = {
  gameId: number
  fav: string
  dog: string
  margin: number
  total: number
}

export function SlateProjectionsChart({ games }: { games: TodayGame[] }) {
  const rows: Row[] = games
    .map((g): Row | null => {
      const hr = g.projection?.expectedHomeRuns
      const ar = g.projection?.expectedAwayRuns
      if (hr == null || ar == null) return null
      const favHome = hr >= ar
      return {
        gameId: g.gameId,
        fav: favHome ? g.home.abbr : g.away.abbr,
        dog: favHome ? g.away.abbr : g.home.abbr,
        margin: Math.abs(hr - ar),
        total: g.projection?.expectedTotal ?? hr + ar,
      }
    })
    .filter((r): r is Row => r !== null)
    .sort((a, b) => b.margin - a.margin)

  if (rows.length === 0) {
    return <p className="text-zinc-500 text-sm">No projected games yet — lineups may not be posted.</p>
  }
  const maxMargin = Math.max(...rows.map((r) => r.margin), 1)

  return (
    <div className="space-y-1">
      {rows.map((r) => {
        const t = Math.min(r.margin / GLOW_CAP_RUNS, 1) // glow/length intensity
        const widthPct = Math.max(8, (r.margin / maxMargin) * 100)
        return (
          <Link
            key={r.gameId}
            href={`/games/${r.gameId}`}
            className="group flex items-center gap-3 rounded-lg px-2 py-1.5 hover:bg-white/5 transition-colors"
          >
            <div
              className="w-12 shrink-0 text-right text-sm font-semibold tabular-nums"
              style={{
                color: `rgba(110, 231, 183, ${0.7 + 0.3 * t})`,
                textShadow: `0 0 ${4 + 9 * t}px rgba(52, 211, 153, ${0.3 + 0.45 * t})`,
              }}
            >
              {r.fav}
            </div>
            <div className="relative h-6 flex-1 overflow-hidden rounded bg-white/5">
              <div
                className="absolute inset-y-0 left-0 rounded"
                style={{ width: `${widthPct}%`, background: `rgba(52, 211, 153, ${0.2 + 0.45 * t})` }}
              />
              <span className="absolute inset-y-0 left-2 flex items-center font-mono text-[11px] text-zinc-200">
                +{r.margin.toFixed(1)} R
              </span>
            </div>
            <div className="w-16 shrink-0 text-xs text-zinc-500">vs {r.dog}</div>
            <div className="w-16 shrink-0 text-right font-mono text-[11px] text-zinc-500">
              {r.total.toFixed(1)} tot
            </div>
          </Link>
        )
      })}
    </div>
  )
}
