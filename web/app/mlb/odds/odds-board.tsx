'use client'

import { Fragment, useMemo, useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { bestPlaysQueryOptions, hitRatesQueryOptions, lineShopQueryOptions } from '@/lib/api'
import type { BestPlay, HitRate, LineShop } from '@/lib/types'
import { cn } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

const MARKET_LABEL: Record<string, string> = {
  moneyline: 'Moneyline',
  run_line: 'Run line',
  total: 'Total',
  hit: 'Hit',
  hr: 'Home run',
  pitcher_k: 'Strikeouts',
  pitcher_outs: 'Outs',
}

function amer(n: number) {
  return n > 0 ? `+${n}` : `${n}`
}

function pct(v: number | null) {
  if (v == null) return '—'
  return (v * 100).toFixed(1) + '%'
}

function signedPct(v: number) {
  return (v > 0 ? '+' : '') + (v * 100).toFixed(1) + '%'
}

// Edge = model − fair (no-vig). This is the board's headline metric; positive means our
// model gives the side a better chance than the de-vigged market does.
function edgeOf(r: BestPlay): number | null {
  return r.fairProb == null ? null : r.modelProb - r.fairProb
}

function edgeClass(edge: number | null) {
  if (edge == null) return 'text-zinc-600'
  if (edge > 0.03) return 'text-emerald-400 font-semibold'
  if (edge > 0) return 'text-emerald-300'
  if (edge > -0.03) return 'text-zinc-400'
  return 'text-rose-300'
}

function evClass(ev: number) {
  if (ev > 0.05) return 'text-emerald-400'
  if (ev > 0) return 'text-emerald-300'
  if (ev > -0.05) return 'text-zinc-500'
  return 'text-rose-300/80'
}

// Hit-rate "traffic light" — Outlier's thresholds: green ≥65%, amber 45–65%, red <45%.
function hrTone(v: number | null): string {
  if (v == null) return 'text-zinc-600'
  if (v >= 0.65) return 'text-emerald-400'
  if (v >= 0.45) return 'text-amber-300'
  return 'text-rose-400'
}

function hrPct(v: number | null): string {
  return v == null ? '—' : Math.round(v * 100) + '%'
}

// Last-10 / last-20 / season clear-rate for a prop's line, color-coded.
function HitRateCell({ hr }: { hr: HitRate | undefined }) {
  if (!hr) return <span className="text-zinc-600">—</span>
  return (
    <span className="inline-flex items-center gap-1 font-mono tabular-nums text-xs">
      <span className={hrTone(hr.l10)} title={`Last 10 games (n=${Math.min(hr.n20, 10)})`}>
        {hrPct(hr.l10)}
      </span>
      <span className="text-zinc-700">·</span>
      <span className={hrTone(hr.l20)} title={`Last 20 games (n=${hr.n20})`}>{hrPct(hr.l20)}</span>
      <span className="text-zinc-700">·</span>
      <span className={hrTone(hr.season)} title={`Season (n=${hr.nSeason})`}>{hrPct(hr.season)}</span>
    </span>
  )
}

// "AWY @ HOM" → team abbr for a home/away side.
function teamForSide(matchup: string, side: string): string {
  const parts = matchup.split(' @ ')
  if (parts.length !== 2) return side
  return side === 'home' ? parts[1] : parts[0]
}

function sideLabel(r: BestPlay): { text: string; tone: 'over' | 'under' | 'team' } {
  if (r.side === 'over') return { text: 'Over', tone: 'over' }
  if (r.side === 'under') return { text: 'Under', tone: 'under' }
  return { text: teamForSide(r.matchup, r.side), tone: 'team' }
}

function lineLabel(r: BestPlay): string {
  if (r.line == null) return '—'
  if (r.market === 'run_line' && r.line > 0) return `+${r.line}`
  return `${r.line}`
}

// Player props → the player; game markets → the matchup.
function subject(r: BestPlay): string {
  return r.playerName ?? r.matchup
}

const SIDE_TONE: Record<'over' | 'under' | 'team', string> = {
  over: 'bg-emerald-500/10 text-emerald-300 border-emerald-400/30',
  under: 'bg-amber-500/10 text-amber-300 border-amber-400/30',
  team: 'bg-cyan-500/10 text-cyan-300 border-cyan-400/30',
}

// Positive-edge plays are the point of the board; let the user hide the rest.
type Filter = 'positive' | 'all'

export function OddsBoard() {
  const [filter, setFilter] = useState<Filter>('positive')
  const [expanded, setExpanded] = useState<string | null>(null)
  const { data, isPending, isError } = useQuery(bestPlaysQueryOptions(undefined, 100))
  const { data: hitRateData } = useQuery(hitRatesQueryOptions())
  const { data: lineShopData } = useQuery(lineShopQueryOptions())

  // Join key: playerId + market (only hit/hr props carry a hit rate).
  const hitRates = useMemo(() => {
    const m = new Map<string, HitRate>()
    for (const h of hitRateData ?? []) m.set(`${h.playerId}:${h.market}`, h)
    return m
  }, [hitRateData])

  // Join key: gameId:playerId:market:side:line (matches the API's line-shop key).
  const lineShop = useMemo(() => {
    const m = new Map<string, LineShop>()
    for (const ls of lineShopData ?? []) m.set(ls.key, ls)
    return m
  }, [lineShopData])

  const rows: BestPlay[] = data ?? []
  const shown = filter === 'positive' ? rows.filter((r) => (edgeOf(r) ?? r.evPct) > 0) : rows

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <div className={microLabel}>Odds</div>
      <h1 className="text-2xl font-bold tracking-tight text-zinc-100 mt-1 mb-2">Best Lines</h1>
      <p className="text-sm text-zinc-400 mb-5 max-w-2xl">
        Today&apos;s best available price for each market, ranked by{' '}
        <span className="text-zinc-200">edge</span> — our model probability minus the{' '}
        <span className="text-zinc-200">fair</span> (no-vig) market probability. We strip the
        bookmaker&apos;s margin out of both sides before comparing, so a juiced favorite no longer
        makes its opposite side look like free money. Game markets use a Poisson run model; hit/HR
        use the batter projections.
      </p>

      <div className="flex items-center gap-2 mb-4">
        <span className={microLabel}>Show</span>
        {(['positive', 'all'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              'text-xs px-3 py-1 rounded border transition-colors',
              filter === f
                ? 'bg-cyan-500/15 text-cyan-300 border-cyan-400/40'
                : 'bg-white/5 text-zinc-400 border-white/10 hover:text-zinc-200 hover:border-white/20',
            )}
          >
            {f === 'positive' ? '+Edge only' : 'All'}
          </button>
        ))}
      </div>

      {isPending ? (
        <p className="text-zinc-400">Loading odds…</p>
      ) : isError ? (
        <p className="text-rose-400">Failed to load odds.</p>
      ) : rows.length === 0 ? (
        <p className="text-amber-300 bg-amber-400/10 border border-amber-400/30 rounded-xl p-4 text-sm">
          No odds loaded yet. Run <span className="font-mono">refresh-odds</span> (needs{' '}
          <span className="font-mono">ODDS_API_KEY</span>, or{' '}
          <span className="font-mono">--sample</span> for fixtures).
        </p>
      ) : (
        <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={microLabel}>
                  <th className="px-3 py-2 text-left font-medium">Player / Game</th>
                  <th className="px-3 py-2 text-left font-medium">Type</th>
                  <th
                    className="px-3 py-2 text-left font-medium"
                    title="Clear-rate vs the prop line — last 10 · last 20 · season"
                  >
                    Hit rate <span className="text-zinc-600 normal-case">L10·20·Szn</span>
                  </th>
                  <th className="px-3 py-2 text-left font-medium">Side</th>
                  <th className="px-3 py-2 text-right font-medium">Line</th>
                  <th className="px-3 py-2 text-right font-medium">Best price</th>
                  <th
                    className="px-3 py-2 text-right font-medium"
                    title="Books posted for this prop — click to compare every price"
                  >
                    Books
                  </th>
                  <th className="px-3 py-2 text-right font-medium" title="No-vig market probability">
                    Fair
                  </th>
                  <th className="px-3 py-2 text-right font-medium">Model</th>
                  <th className="px-3 py-2 text-right font-medium" title="Model − Fair">
                    Edge
                  </th>
                  <th className="px-3 py-2 text-right font-medium" title="Expected value at the best price">
                    EV
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => {
                  const s = sideLabel(r)
                  const edge = edgeOf(r)
                  const hr = r.playerId != null ? hitRates.get(`${r.playerId}:${r.market}`) : undefined
                  const lsKey =
                    r.playerId != null && r.line != null
                      ? `${r.gameId}:${r.playerId}:${r.market}:${r.side}:${r.line}`
                      : null
                  const ls = lsKey ? lineShop.get(lsKey) : undefined
                  const isExpanded = lsKey != null && expanded === lsKey
                  return (
                    <Fragment key={`${r.gameId}-${r.market}-${r.selection}-${i}`}>
                    <tr
                      className="border-t border-white/5 hover:bg-white/[0.02] transition-colors"
                    >
                      <td className="px-3 py-2 text-zinc-100 whitespace-nowrap">
                        {r.playerId ? (
                          <Link href={`/mlb/players/${r.playerId}`} className="hover:text-cyan-400 transition-colors">
                            {subject(r)}
                          </Link>
                        ) : (
                          <Link href={`/mlb/games/${r.gameId}`} className="hover:text-cyan-400 transition-colors">
                            {subject(r)}
                          </Link>
                        )}
                        {r.playerName && (
                          <Link
                            href={`/mlb/games/${r.gameId}`}
                            className="text-zinc-500 hover:text-cyan-400 transition-colors font-mono text-xs ml-1.5"
                          >
                            {r.matchup}
                          </Link>
                        )}
                      </td>
                      <td className="px-3 py-2 text-zinc-300 whitespace-nowrap">
                        {MARKET_LABEL[r.market] ?? r.market}
                      </td>
                      <td className="px-3 py-2 whitespace-nowrap">
                        <HitRateCell hr={hr} />
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={cn(
                            'inline-block px-1.5 py-0.5 rounded border text-xs font-medium',
                            SIDE_TONE[s.tone],
                          )}
                        >
                          {s.text}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">
                        {lineLabel(r)}
                      </td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        <span className="font-mono tabular-nums text-zinc-100">{amer(r.priceAmerican)}</span>{' '}
                        <span className="text-zinc-500 text-xs">{r.bestBook}</span>
                      </td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        {ls && ls.quotes.length > 0 ? (
                          <button
                            onClick={() => setExpanded(isExpanded ? null : lsKey)}
                            className={cn(
                              'font-mono tabular-nums text-xs px-1.5 py-0.5 rounded border transition-colors',
                              isExpanded
                                ? 'bg-cyan-500/15 text-cyan-300 border-cyan-400/40'
                                : 'bg-white/5 text-zinc-400 border-white/10 hover:text-zinc-200 hover:border-white/20',
                            )}
                          >
                            {ls.quotes.length} {isExpanded ? '▾' : '▸'}
                          </button>
                        ) : (
                          <span className="text-zinc-600">—</span>
                        )}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-400">
                        {pct(r.fairProb)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">
                        {pct(r.modelProb)}
                      </td>
                      <td className={cn('px-3 py-2 text-right font-mono tabular-nums', edgeClass(edge))}>
                        {edge == null ? '—' : signedPct(edge)}
                      </td>
                      <td className={cn('px-3 py-2 text-right font-mono tabular-nums text-xs', evClass(r.evPct))}>
                        {signedPct(r.evPct)}
                      </td>
                    </tr>
                    {isExpanded && ls && (
                      <tr className="bg-white/[0.02] border-t border-white/5">
                        <td colSpan={11} className="px-3 py-2.5">
                          <div className="flex flex-wrap items-center gap-2">
                            <span className={cn(microLabel, 'mr-1')}>Line shop</span>
                            {ls.quotes.map((q, qi) => (
                              <span
                                key={q.book}
                                className={cn(
                                  'inline-flex items-center gap-1.5 px-2 py-1 rounded border text-xs',
                                  qi === 0
                                    ? 'border-emerald-400/40 bg-emerald-500/10 text-emerald-300'
                                    : 'border-white/10 bg-white/5 text-zinc-300',
                                )}
                              >
                                <span className="text-zinc-400">{q.book}</span>
                                <span className="font-mono tabular-nums">{amer(q.priceAmerican)}</span>
                                {qi === 0 && <span className="text-[10px] uppercase tracking-wide">best</span>}
                              </span>
                            ))}
                          </div>
                        </td>
                      </tr>
                    )}
                    </Fragment>
                  )
                })}
              </tbody>
            </table>
          </div>
          {shown.length === 0 && (
            <p className="px-4 py-6 text-sm text-zinc-500">No positive-edge plays right now.</p>
          )}
        </div>
      )}
    </main>
  )
}
