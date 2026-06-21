'use client'

import { Fragment, useMemo, useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { bestPlaysQueryOptions, hitRatesQueryOptions, lineShopQueryOptions } from '@/lib/api'
import type { BestPlay, HitRate, LineShop } from '@/lib/types'
import { cn } from '@/lib/utils'
import { MARKET_LABEL, teamForSide } from '@/lib/odds'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

// The default view only shows lines we'd actually consider: the model makes the
// side at least this likely AND it carries a positive de-vigged edge — capped at
// the top few per market so one prop type (hits) can't flood the board. The
// toggles re-reveal everything else.
const MIN_MODEL_PROB = 0.5
const LIKED_PER_MARKET = 5

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
// Applied to the SEASON rate only: short-window streaks are hot-hand noise (and our
// own backtests treat them that way), so L10/L20 render as muted context, not signal.
function hrTone(v: number | null): string {
  if (v == null) return 'text-zinc-600'
  if (v >= 0.65) return 'text-emerald-400'
  if (v >= 0.45) return 'text-amber-300'
  return 'text-rose-400'
}

function hrPct(v: number | null): string {
  return v == null ? '—' : Math.round(v * 100) + '%'
}

// Season clear-rate (colored) leads; last-10/last-20 follow as muted context.
function HitRateCell({ hr }: { hr: HitRate | undefined }) {
  if (!hr) return <span className="text-zinc-600">—</span>
  return (
    <span className="inline-flex items-center gap-1 font-mono tabular-nums text-xs">
      <span className={hrTone(hr.season)} title={`Season (n=${hr.nSeason})`}>{hrPct(hr.season)}</span>
      <span className="text-zinc-700">·</span>
      <span className="text-zinc-500" title={`Last 10 games (n=${Math.min(hr.n20, 10)}) — context, not signal`}>
        {hrPct(hr.l10)}
      </span>
      <span className="text-zinc-700">·</span>
      <span className="text-zinc-500" title={`Last 20 games (n=${hr.n20}) — context, not signal`}>
        {hrPct(hr.l20)}
      </span>
    </span>
  )
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

// Tiered filters: what we like (model% floor + edge) → any positive edge → everything.
type Filter = 'liked' | 'positive' | 'all'

function isLiked(r: BestPlay): boolean {
  const edge = edgeOf(r)
  return edge != null && edge > 0 && r.modelProb >= MIN_MODEL_PROB
}

function isPositive(r: BestPlay): boolean {
  return (edgeOf(r) ?? r.evPct) > 0
}

// Liked rows, best edge first, at most LIKED_PER_MARKET from any one market.
function likedRows(rows: BestPlay[]): BestPlay[] {
  const byMarket = new Map<string, BestPlay[]>()
  for (const r of rows) {
    if (!isLiked(r)) continue
    const list = byMarket.get(r.market) ?? []
    list.push(r)
    byMarket.set(r.market, list)
  }
  const out: BestPlay[] = []
  for (const list of byMarket.values()) {
    list.sort((a, b) => (edgeOf(b) ?? 0) - (edgeOf(a) ?? 0))
    out.push(...list.slice(0, LIKED_PER_MARKET))
  }
  return out.sort((a, b) => (edgeOf(b) ?? 0) - (edgeOf(a) ?? 0))
}

const EMPTY_MESSAGE: Record<Filter, string> = {
  liked: `Nothing clears the bar right now (model ≥ ${MIN_MODEL_PROB * 100}% with a positive edge) — widen to +Edge or All to see the rest of the board.`,
  positive: 'No positive-edge plays right now.',
  all: 'No plays on the board.',
}

// One labelled metric in the mobile card's stat grid.
function Metric({ label, value, className }: { label: string; value: string; className?: string }) {
  return (
    <div>
      <div className={microLabel}>{label}</div>
      <div className={cn('font-mono tabular-nums text-sm', className)}>{value}</div>
    </div>
  )
}

// Mobile-only card rendering of a single play — the same data as one table row,
// stacked so it reads on a narrow screen. Reuses every table-row helper.
function PlayCard({
  r,
  hr,
  ls,
  isExpanded,
  onToggle,
}: {
  r: BestPlay
  hr: HitRate | undefined
  ls: LineShop | undefined
  isExpanded: boolean
  onToggle: () => void
}) {
  const s = sideLabel(r)
  const edge = edgeOf(r)
  return (
    <div className="rounded-xl border border-white/10 bg-[#0e1015] p-4">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <Link
            href={r.playerId ? `/mlb/players/${r.playerId}` : `/mlb/games/${r.gameId}`}
            className="font-medium text-zinc-100 hover:text-cyan-400 transition-colors"
          >
            {subject(r)}
          </Link>
          <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-xs text-zinc-500">
            <span>{MARKET_LABEL[r.market] ?? r.market}</span>
            {r.playerName && (
              <Link
                href={`/mlb/games/${r.gameId}`}
                className="font-mono hover:text-cyan-400 transition-colors"
              >
                {r.matchup}
              </Link>
            )}
          </div>
        </div>
        <span
          className={cn(
            'shrink-0 inline-block rounded border px-1.5 py-0.5 text-xs font-medium whitespace-nowrap',
            SIDE_TONE[s.tone],
          )}
        >
          {s.text} {lineLabel(r)}
        </span>
      </div>

      <div className="mt-3 grid grid-cols-4 gap-2 text-center">
        <Metric label="Model" value={pct(r.modelProb)} className="text-zinc-300" />
        <Metric label="Fair" value={pct(r.fairProb)} className="text-zinc-400" />
        <Metric label="Edge" value={edge == null ? '—' : signedPct(edge)} className={edgeClass(edge)} />
        <Metric label="EV" value={signedPct(r.evPct)} className={evClass(r.evPct)} />
      </div>

      <div className="mt-3 flex items-center justify-between gap-2 text-sm">
        <div>
          <span className="font-mono tabular-nums text-zinc-100">{amer(r.priceAmerican)}</span>{' '}
          <span className="text-xs text-zinc-500">{r.bestBook}</span>
        </div>
        {ls && ls.quotes.length > 0 && (
          <button
            onClick={onToggle}
            className={cn(
              'rounded border px-2 py-1 font-mono text-xs tabular-nums transition-colors',
              isExpanded
                ? 'border-cyan-400/40 bg-cyan-500/15 text-cyan-300'
                : 'border-white/10 bg-white/5 text-zinc-400 hover:border-white/20 hover:text-zinc-200',
            )}
          >
            {ls.quotes.length} books {isExpanded ? '▾' : '▸'}
          </button>
        )}
      </div>

      {hr && (
        <div className="mt-2 flex items-center gap-1.5">
          <span className={microLabel}>Hit rate</span>
          <HitRateCell hr={hr} />
        </div>
      )}

      {isExpanded && ls && (
        <div className="mt-3 flex flex-wrap items-center gap-2 border-t border-white/5 pt-3">
          {ls.quotes.map((q, qi) => (
            <span
              key={q.book}
              className={cn(
                'inline-flex items-center gap-1.5 rounded border px-2 py-1 text-xs',
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
      )}
    </div>
  )
}

export function OddsBoard() {
  const [filter, setFilter] = useState<Filter>('liked')
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
  const liked = likedRows(rows)
  const shown = filter === 'liked' ? liked : filter === 'positive' ? rows.filter(isPositive) : rows

  const filterLabel = (f: Filter) =>
    f === 'liked'
      ? `What we like (${liked.length})`
      : f === 'positive'
        ? `+Edge (${rows.filter(isPositive).length})`
        : `All (${rows.length})`

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
        use the batter projections. By default we only show{' '}
        <span className="text-zinc-200">what we like</span>: sides the model makes at least{' '}
        {MIN_MODEL_PROB * 100}% likely with a positive edge, capped at the top{' '}
        {LIKED_PER_MARKET} per market.{' '}
        <Link href="/faq" className="text-cyan-400 hover:text-cyan-300">
          What do Fair / Model / Edge / EV mean?
        </Link>
      </p>

      <div className="flex items-center gap-2 mb-4">
        <span className={microLabel}>Show</span>
        {(['liked', 'positive', 'all'] as const).map((f) => (
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
            {filterLabel(f)}
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
        <>
        {/* mobile: stacked cards */}
        <div className="space-y-3 md:hidden">
          {shown.length === 0 ? (
            <p className="rounded-xl border border-white/10 bg-[#0e1015] px-4 py-6 text-sm text-zinc-500">
              {EMPTY_MESSAGE[filter]}
            </p>
          ) : (
            shown.map((r, i) => {
              const hr = r.playerId != null ? hitRates.get(`${r.playerId}:${r.market}`) : undefined
              const lsKey =
                r.playerId != null && r.line != null
                  ? `${r.gameId}:${r.playerId}:${r.market}:${r.side}:${r.line}`
                  : null
              const ls = lsKey ? lineShop.get(lsKey) : undefined
              return (
                <PlayCard
                  key={`${r.gameId}-${r.market}-${r.selection}-${i}`}
                  r={r}
                  hr={hr}
                  ls={ls}
                  isExpanded={lsKey != null && expanded === lsKey}
                  onToggle={() => lsKey && setExpanded(expanded === lsKey ? null : lsKey)}
                />
              )
            })
          )}
        </div>

        {/* desktop: table */}
        <div className="hidden bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden md:block">
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
                    Hit rate <span className="text-zinc-600 normal-case">Szn·L10·L20</span>
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
            <p className="px-4 py-6 text-sm text-zinc-500">{EMPTY_MESSAGE[filter]}</p>
          )}
        </div>
        </>
      )}
    </main>
  )
}
