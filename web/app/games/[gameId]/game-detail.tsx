'use client'

import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ArrowLeft, ArrowUp } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import { api } from '@/lib/api'
import type { BatterProjection, Adjustments, Probabilities } from '@/lib/types'
import { cn, parseApiDate } from '@/lib/utils'

// ── helpers ─────────────────────────────────────────────────────────────────

function degreesToCardinal(deg: number): string {
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
  return dirs[Math.round(deg / 45) % 8]
}

function pct(v: number | null | undefined) {
  if (v == null) return '—'
  return (v * 100).toFixed(1) + '%'
}

function fixed2(v: number | null | undefined) {
  if (v == null) return '—'
  return v.toFixed(2)
}

function hrClass(p: number) {
  if (p > 0.12) return 'text-green-700 font-semibold'
  if (p > 0.08) return 'text-green-600'
  if (p >= 0.05) return 'text-zinc-700'
  return 'text-zinc-400'
}

function hitClass(p: number) {
  if (p > 0.75) return 'text-green-600'
  if (p < 0.5) return 'text-red-500'
  return 'text-zinc-700'
}

function kClass(p: number) {
  return p > 0.6 ? 'text-red-500' : 'text-zinc-700'
}

type SortCol = 'hit1plus' | 'hit2plus' | 'hr' | 'k1plus'

function pitcherQualityLabel(q: string | null): string {
  if (q === 'matchup') return 'Matchup sample'
  if (q === 'overall') return 'Overall pitcher stats'
  if (q === 'league_avg') return 'Unknown pitcher (league avg)'
  return ''
}

function adjTooltip(
  finalVal: number,
  adjs: Adjustments,
  isHr: boolean,
  pitcherDataQuality: string | null,
): string {
  const w = isHr ? adjs.weatherHr : adjs.weatherHit
  const combined = (adjs.park ?? 1) * (adjs.pitcher ?? 1) * (w ?? 1)
  const base = combined !== 0 ? finalVal / combined : finalVal
  const f = (n: number | null | undefined) => (n != null ? n.toFixed(3) : '—')
  const breakdown = `Base: ${f(base)} · Park ×${f(adjs.park)} · Pitcher ×${f(adjs.pitcher)} · Weather ×${f(w)} → ${f(finalVal)}`
  const ql = pitcherQualityLabel(pitcherDataQuality)
  return ql ? `${breakdown}\n${ql}` : breakdown
}

// ── batter table ─────────────────────────────────────────────────────────────

function BatterTable({
  batters,
  sortCol,
  sortDir,
  onSort,
}: {
  batters: BatterProjection[]
  sortCol: SortCol
  sortDir: 'asc' | 'desc'
  onSort: (col: SortCol) => void
}) {
  const sorted = [...batters].sort((a, b) => {
    const av = a.probabilities[sortCol] ?? 0
    const bv = b.probabilities[sortCol] ?? 0
    return sortDir === 'desc' ? bv - av : av - bv
  })

  function ColHeader({ col, label }: { col: SortCol; label: string }) {
    const active = sortCol === col
    return (
      <th
        className={cn(
          'px-2 py-2 text-right cursor-pointer select-none whitespace-nowrap',
          active ? 'text-blue-600 underline underline-offset-2' : 'text-zinc-500',
        )}
        onClick={() => onSort(col)}
      >
        {label}
      </th>
    )
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-zinc-200 text-xs font-medium">
            <th className="px-2 py-2 text-left text-zinc-500">Player</th>
            <th className="px-2 py-2 text-right text-zinc-500">xPA</th>
            <ColHeader col="hit1plus" label="P(H≥1)" />
            <ColHeader col="hit2plus" label="P(H≥2)" />
            <ColHeader col="hr" label="P(HR)" />
            <ColHeader col="k1plus" label="P(K)" />
            <th className="px-2 py-2 text-right text-zinc-500">xH</th>
            <th className="px-2 py-2 text-right text-zinc-500">xTB</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((b) => {
            const p = b.probabilities
            const a = b.adjustments
            return (
              <tr
                key={b.player.id}
                className="border-b border-zinc-100 hover:bg-zinc-50"
              >
                <td className="px-2 py-2">
                  <Link
                    href={`/players/${b.player.id}`}
                    className="hover:underline font-medium"
                  >
                    {b.player.name}
                  </Link>
                  <span className="ml-1.5 text-xs text-zinc-400">
                    {b.player.bats && `(${b.player.bats})`}
                    {b.player.position && ` · ${b.player.position}`}
                  </span>
                </td>
                <td className="px-2 py-2 text-right tabular-nums text-zinc-600">
                  {fixed2(b.expectedPa)}
                </td>
                <td
                  className={cn('px-2 py-2 text-right tabular-nums', hitClass(p.hit1plus))}
                  title={adjTooltip(p.hit1plus, a, false, b.pitcherDataQuality)}
                >
                  {pct(p.hit1plus)}
                </td>
                <td
                  className="px-2 py-2 text-right tabular-nums text-zinc-700"
                  title={adjTooltip(p.hit2plus, a, false, b.pitcherDataQuality)}
                >
                  {pct(p.hit2plus)}
                </td>
                <td
                  className={cn('px-2 py-2 text-right tabular-nums', hrClass(p.hr))}
                  title={adjTooltip(p.hr, a, true, b.pitcherDataQuality)}
                >
                  {pct(p.hr)}
                </td>
                <td
                  className={cn('px-2 py-2 text-right tabular-nums', kClass(p.k1plus))}
                  title={adjTooltip(p.k1plus, a, false, b.pitcherDataQuality)}
                >
                  {pct(p.k1plus)}
                </td>
                <td className="px-2 py-2 text-right tabular-nums text-zinc-600">
                  {fixed2(b.expectedHits)}
                </td>
                <td className="px-2 py-2 text-right tabular-nums text-zinc-600">
                  {fixed2(b.expectedTotalBases)}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────────────

export function GameDetail({ gameId }: { gameId: number }) {
  const [sortCol, setSortCol] = useState<SortCol>('hit1plus')
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const { data, isPending, isError } = useQuery({
    queryKey: ['game', 'projections', gameId],
    queryFn: () => api.gameProjections(gameId),
  })

  // also fetch today's games to show header info
  const { data: games } = useQuery({
    queryKey: ['games', 'today'],
    queryFn: api.todayGames,
  })
  const game = games?.find((g) => g.gameId === gameId)

  function handleSort(col: SortCol) {
    if (col === sortCol) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortCol(col)
      setSortDir('desc')
    }
  }

  if (isPending) return <div className="p-8 text-zinc-400">Loading projections…</div>
  if (isError) return <div className="p-8 text-red-500">Failed to load projections.</div>

  // Away batters face the home SP, and vice versa.
  const homeSpHand = data.away.batters[0]?.opposingPitcher.throws ?? null
  const awaySpHand = data.home.batters[0]?.opposingPitcher.throws ?? null

  const homeRuns = game?.projection?.expectedHomeRuns ?? 0
  const awayRuns = game?.projection?.expectedAwayRuns ?? 0
  const total = homeRuns + awayRuns
  const homePct = total > 0 ? (homeRuns / total) * 100 : 50

  return (
    <main className="max-w-7xl mx-auto w-full px-4 py-8">
      {/* back link */}
      <Link href="/" className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-800 mb-6">
        <ArrowLeft size={14} /> All Games
      </Link>

      {/* header */}
      {game && (
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight mb-1">
            {game.away.abbr} @ {game.home.abbr}
          </h1>
          <div className="flex flex-wrap gap-3 text-sm text-zinc-500 items-center">
            <span>{format(parseApiDate(game.startTimeUtc), 'h:mm a · MMMM d, yyyy')}</span>
            <span>·</span>
            <span>{game.stadium.name}</span>
            {game.stadium.isDome && (
              <span className="text-xs bg-blue-50 text-blue-600 border border-blue-200 rounded px-1.5">
                Dome
              </span>
            )}
            {!game.stadium.isDome && game.weather.windDirDeg != null && (
              <span className="inline-flex items-center gap-1 text-xs bg-zinc-100 rounded px-2 py-0.5">
                {game.weather.tempF}°F ·{' '}
                <ArrowUp
                  size={11}
                  style={{ transform: `rotate(${game.weather.windDirDeg}deg)` }}
                />
                {game.weather.windMph} mph
              </span>
            )}
          </div>
          {/* probables */}
          {game.probables && (
            <div className="mt-2 flex gap-4 text-sm">
              {game.probables.home && (
                <span className="inline-flex items-center gap-1.5 bg-zinc-100 rounded px-2 py-0.5">
                  <span className="text-zinc-500 text-xs">{game.home.abbr} SP</span>
                  {game.probables.home.name}
                  {homeSpHand && (
                    <span className="text-xs font-medium text-zinc-500 bg-zinc-200 rounded px-1">
                      {homeSpHand === 'L' ? 'LHP' : 'RHP'}
                    </span>
                  )}
                </span>
              )}
              {game.probables.away && (
                <span className="inline-flex items-center gap-1.5 bg-zinc-100 rounded px-2 py-0.5">
                  <span className="text-zinc-500 text-xs">{game.away.abbr} SP</span>
                  {game.probables.away.name}
                  {awaySpHand && (
                    <span className="text-xs font-medium text-zinc-500 bg-zinc-200 rounded px-1">
                      {awaySpHand === 'L' ? 'LHP' : 'RHP'}
                    </span>
                  )}
                </span>
              )}
            </div>
          )}
        </div>
      )}

      {/* expected runs bar */}
      {game?.projection && (
        <div className="mb-8 bg-white border border-zinc-200 rounded-xl p-5">
          <div className="flex justify-between text-sm font-medium mb-2">
            <span>{game.home.abbr} <span className="text-zinc-400 font-normal">home</span></span>
            <span className="text-zinc-500">Expected Runs</span>
            <span>{game.away.abbr} <span className="text-zinc-400 font-normal">away</span></span>
          </div>
          <div className="flex h-8 rounded overflow-hidden gap-0.5">
            <div
              className="bg-blue-600 flex items-center justify-end pr-2 text-white text-sm font-bold tabular-nums"
              style={{ width: `${homePct}%` }}
            >
              {homeRuns.toFixed(2)}
            </div>
            <div
              className="bg-zinc-400 flex items-center justify-start pl-2 text-white text-sm font-bold tabular-nums"
              style={{ width: `${100 - homePct}%` }}
            >
              {awayRuns.toFixed(2)}
            </div>
          </div>
          <div className="text-center text-xs text-zinc-400 mt-1">
            Total: {game.projection.expectedTotal.toFixed(2)} R
          </div>
        </div>
      )}

      {/* empty state */}
      {data.home.batters.length === 0 && data.away.batters.length === 0 && (
        <p className="text-amber-600 bg-amber-50 rounded p-4">
          Projection pending — probable pitchers or lineups not yet confirmed.
        </p>
      )}

      {/* sort toggle */}
      {(data.home.batters.length > 0 || data.away.batters.length > 0) && (
        <>
          <div className="flex items-center gap-2 mb-4">
            <span className="text-xs text-zinc-500">Sort:</span>
            <button
              onClick={() => setSortDir('desc')}
              className={cn(
                'text-xs px-3 py-1 rounded border',
                sortDir === 'desc'
                  ? 'bg-zinc-900 text-white border-zinc-900'
                  : 'bg-white text-zinc-600 border-zinc-300 hover:border-zinc-500',
              )}
            >
              Most likely outcomes
            </button>
            <button
              onClick={() => setSortDir('asc')}
              className={cn(
                'text-xs px-3 py-1 rounded border',
                sortDir === 'asc'
                  ? 'bg-zinc-900 text-white border-zinc-900'
                  : 'bg-white text-zinc-600 border-zinc-300 hover:border-zinc-500',
              )}
            >
              Least likely outcomes
            </button>
          </div>

          {/* tables */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {/* home */}
            <div className="bg-white border border-zinc-200 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-zinc-100 font-semibold text-sm">
                {data.home.teamAbbr ?? game?.home.abbr} — Home
              </div>
              {data.home.batters.length > 0 ? (
                <BatterTable
                  batters={data.home.batters}
                  sortCol={sortCol}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
              ) : (
                <p className="px-4 py-6 text-sm text-zinc-400">No projections available.</p>
              )}
            </div>

            {/* away */}
            <div className="bg-white border border-zinc-200 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-zinc-100 font-semibold text-sm">
                {data.away.teamAbbr ?? game?.away.abbr} — Away
              </div>
              {data.away.batters.length > 0 ? (
                <BatterTable
                  batters={data.away.batters}
                  sortCol={sortCol}
                  sortDir={sortDir}
                  onSort={handleSort}
                />
              ) : (
                <p className="px-4 py-6 text-sm text-zinc-400">No projections available.</p>
              )}
            </div>
          </div>

          <p className="text-xs text-zinc-400 mt-3">
            Hover probability cells to see adjustment breakdown (Park · Pitcher · Weather).
          </p>
        </>
      )}
    </main>
  )
}
