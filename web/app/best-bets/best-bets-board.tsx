'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Flame } from 'lucide-react'
import type { BatterPropOdds, FlatBatterPick } from '@/lib/types'
import { batterPropOddsQueryOptions } from '@/lib/api'
import { usePicks } from '@/components/home/use-picks'
import { cn } from '@/lib/utils'
import {
  bookLabel,
  expectedValue,
  formatAmerican,
  impliedFromAmerican,
} from '@/lib/odds'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

// ── tunable conviction floors ─────────────────────────────────────────────────
// A market only surfaces a headline pick when its best candidate clears the bar;
// otherwise we say so rather than forcing a weak lean.
const HIT_FLOOR = 0.68 // P(H≥1)
const HR_FLOOR = 0.09 // P(HR)
const TB_FLOOR = 1.7 // expected total bases
// "Bet of the Day" only fires on a priced pick with at least this model edge (EV).
const BOTD_MIN_EV = 0.05

type Market = 'hit' | 'hr' | 'tb'

interface Selection {
  market: Market
  pick: FlatBatterPick
  /** Win probability for hit/hr; null for tb (no binary prob). */
  modelProb: number | null
  /** Display metric: probability for hit/hr, xTB for tb. */
  metric: number
  odds: BatterPropOdds | null
  ev: number | null
  edge: number | null
}

function pct(v: number | null | undefined) {
  if (v == null) return '—'
  return (v * 100).toFixed(0) + '%'
}

function hand(pick: FlatBatterPick) {
  return pick.opposingPitcherThrows === 'L' ? 'LHP' : 'RHP'
}

function propKey(gameId: number, playerId: number, market: string) {
  return `${gameId}-${playerId}-${market}`
}

// ── selection: best candidate per market, attaching odds + edge ───────────────

function buildSelection(
  market: Market,
  picks: FlatBatterPick[],
  oddsByKey: Map<string, BatterPropOdds>,
): Selection | null {
  let best: FlatBatterPick | null = null
  let bestMetric = -Infinity

  for (const p of picks) {
    const m =
      market === 'hit'
        ? p.batter.probabilities.hit1plus
        : market === 'hr'
          ? p.batter.probabilities.hr
          : p.batter.expectedTotalBases
    if (m == null) continue
    if (m > bestMetric) {
      bestMetric = m
      best = p
    }
  }

  if (!best) return null
  const floor = market === 'hit' ? HIT_FLOOR : market === 'hr' ? HR_FLOOR : TB_FLOOR
  if (bestMetric < floor) return null

  const modelProb =
    market === 'hit'
      ? best.batter.probabilities.hit1plus
      : market === 'hr'
        ? best.batter.probabilities.hr
        : null

  // tb has no ingested prop market, so it never carries odds.
  const odds =
    market === 'tb'
      ? null
      : oddsByKey.get(propKey(best.gameId, best.batter.player.id, market)) ?? null

  let ev: number | null = null
  let edge: number | null = null
  if (odds?.priceAmerican != null && modelProb != null) {
    ev = expectedValue(modelProb, odds.priceAmerican)
    edge = modelProb - impliedFromAmerican(odds.priceAmerican)
  }

  return { market, pick: best, modelProb, metric: bestMetric, odds, ev, edge }
}

// ── explanation strings ───────────────────────────────────────────────────────

const MARKET_VERB: Record<Market, string> = {
  hit: 'to record a hit',
  hr: 'to hit a home run',
  tb: 'for total bases',
}

function matchupClause(pick: FlatBatterPick): string {
  const x = pick.batter.matchupXwoba
  return x != null ? `, ${x.toFixed(3)} xwOBA matchup` : ''
}

function oddsClause(sel: Selection): string {
  const o = sel.odds
  if (!o || o.priceAmerican == null) return ''
  const implied = pct(impliedFromAmerican(o.priceAmerican))
  const edgeStr =
    sel.edge != null && sel.edge > 0 ? `, +${(sel.edge * 100).toFixed(0)}% edge` : ''
  return ` ${bookLabel(o.book)} prices it ${formatAmerican(o.priceAmerican)} (${implied} implied${edgeStr}).`
}

function explain(sel: Selection): string {
  const p = sel.pick
  const who = `${p.batter.player.name}`
  if (sel.market === 'tb') {
    return (
      `${who} projects for ${sel.metric.toFixed(2)} total bases vs ${hand(p)} ` +
      `${p.opposingPitcherName} — ${p.batter.expectedHits.toFixed(2)} expected hits over ` +
      `${p.batter.expectedPa.toFixed(1)} PA${matchupClause(p)}.`
    )
  }
  const lead = `${who} ${MARKET_VERB[sel.market]} — ${pct(sel.modelProb)} model probability vs ${hand(p)} ${p.opposingPitcherName}${matchupClause(p)}.`
  return lead + oddsClause(sel)
}

// ── presentational pieces ─────────────────────────────────────────────────────

function MarketCard({
  title,
  blurb,
  selection,
}: {
  title: string
  blurb: string
  selection: Selection | null
}) {
  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden flex flex-col">
      <div className="px-4 pt-4 pb-3 border-b border-white/10">
        <h2 className="font-semibold tracking-tight text-zinc-100 text-sm">{title}</h2>
        <p className="text-xs text-zinc-500 mt-0.5">{blurb}</p>
      </div>
      {selection ? (
        <SelectionBody selection={selection} />
      ) : (
        <div className="px-4 py-6 text-xs text-zinc-500">
          No strong lean in this market today.
        </div>
      )}
    </div>
  )
}

function SelectionBody({ selection }: { selection: Selection }) {
  const p = selection.pick
  const metricLabel =
    selection.market === 'tb'
      ? `${selection.metric.toFixed(2)} xTB`
      : pct(selection.modelProb)
  return (
    <div className="px-4 py-3 flex flex-col gap-2">
      <div className="flex items-center justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-1.5">
            <Link
              href={`/mlb/players/${p.batter.player.id}`}
              className="font-semibold text-zinc-100 hover:text-cyan-400 transition-colors truncate"
            >
              {p.batter.player.name}
            </Link>
            <span className="text-[11px] text-zinc-500 shrink-0">{p.teamAbbr}</span>
            {!p.lineupConfirmed && (
              <span className="text-[10px] text-amber-300/80 shrink-0" title="Projected lineup">
                proj
              </span>
            )}
          </div>
          <div className="text-[11px] text-zinc-500 truncate">
            vs {p.opponentAbbr} {hand(p)} {p.opposingPitcherName}
          </div>
        </div>
        <div className="text-right shrink-0">
          <div className="font-mono tabular-nums text-lg text-emerald-300 leading-none">
            {metricLabel}
          </div>
          {selection.odds?.priceAmerican != null && (
            <div className="text-[11px] text-zinc-400 font-mono tabular-nums mt-1">
              {bookLabel(selection.odds.book)} {formatAmerican(selection.odds.priceAmerican)}
            </div>
          )}
        </div>
      </div>
      <p className="text-[13px] leading-relaxed text-zinc-400">{explain(selection)}</p>
    </div>
  )
}

function BetOfTheDay({ selection }: { selection: Selection | null }) {
  if (!selection) {
    return (
      <div className="bg-[#0e1015] border border-white/10 rounded-xl px-5 py-5">
        <div className="flex items-center gap-2">
          <span className={microLabel}>Bet of the Day</span>
        </div>
        <p className="mt-2 text-sm text-zinc-400">
          No standout edge on today&apos;s slate — the model doesn&apos;t see a price worth
          backing. Sometimes the sharpest move is to pass.
        </p>
      </div>
    )
  }
  const p = selection.pick
  return (
    <div className="relative bg-gradient-to-br from-cyan-500/10 to-[#0e1015] border border-cyan-400/30 rounded-xl px-5 py-5 overflow-hidden">
      <div className="flex items-center gap-2 mb-2">
        <Flame className="h-4 w-4 text-cyan-300" aria-hidden="true" />
        <span className="text-[10px] uppercase tracking-[0.12em] text-cyan-300 font-semibold">
          Bet of the Day
        </span>
      </div>
      <div className="flex items-baseline gap-2 flex-wrap">
        <Link
          href={`/mlb/players/${p.batter.player.id}`}
          className="text-xl font-bold tracking-tight text-zinc-100 hover:text-cyan-300 transition-colors"
        >
          {p.batter.player.name}
        </Link>
        <span className="text-sm text-zinc-400">{MARKET_VERB[selection.market]}</span>
        {selection.odds?.priceAmerican != null && (
          <span className="font-mono tabular-nums text-sm text-cyan-300">
            {bookLabel(selection.odds.book)} {formatAmerican(selection.odds.priceAmerican)}
          </span>
        )}
      </div>
      <p className="mt-2 text-sm leading-relaxed text-zinc-300">{explain(selection)}</p>
      {selection.ev != null && (
        <p className="mt-2 text-[13px] text-cyan-200/90">
          Our favorite line: model gives it {pct(selection.modelProb)} where the book implies{' '}
          {pct(impliedFromAmerican(selection.odds!.priceAmerican!))} — a{' '}
          <span className="font-semibold">+{(selection.ev * 100).toFixed(0)}% expected value</span>{' '}
          edge, the largest on the board.
        </p>
      )}
    </div>
  )
}

// ── skeletons ─────────────────────────────────────────────────────────────────

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={cn('animate-pulse bg-white/5 rounded', className)} />
}

function LoadingState() {
  return (
    <div className="space-y-4">
      <Skeleton className="h-28 w-full rounded-xl" />
      <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-40 w-full rounded-xl" />
        ))}
      </div>
    </div>
  )
}

// ── page body ─────────────────────────────────────────────────────────────────

export function BestBetsBoard() {
  const { games, picks, isPending, isError, projectionsLoading } = usePicks()
  const { data: propOdds } = useQuery(batterPropOddsQueryOptions())

  const oddsByKey = new Map<string, BatterPropOdds>()
  for (const o of propOdds ?? []) {
    oddsByKey.set(propKey(o.gameId, o.playerId, o.market), o)
  }

  const hitSel = buildSelection('hit', picks, oddsByKey)
  const hrSel = buildSelection('hr', picks, oddsByKey)
  const tbSel = buildSelection('tb', picks, oddsByKey)

  // Bet of the Day: the priced pick with the largest positive expected value.
  const betOfDay = [hitSel, hrSel]
    .filter((s): s is Selection => s != null && s.ev != null && s.ev >= BOTD_MIN_EV)
    .sort((a, b) => (b.ev ?? 0) - (a.ev ?? 0))[0] ?? null

  const projectedGames = games.filter((g) => g.projection)
  const hasContent = picks.length > 0 || projectedGames.length > 0
  const loading = isPending || (projectionsLoading && picks.length === 0)
  const noLeans = !hitSel && !hrSel && !tbSel

  return (
    <main className="max-w-6xl mx-auto w-full px-4 py-8">
      <div className="mb-8">
        <div className={microLabel}>Top Bets</div>
        <h1 className="text-3xl font-bold tracking-tight text-zinc-100 mt-1">Best Bets</h1>
        <p className="text-zinc-500 text-sm mt-1">
          The model&apos;s single favorite in each market today, with the reasoning — and the one
          play it likes most against the book&apos;s price.
          {projectionsLoading && picks.length > 0 && (
            <span className="text-zinc-600"> · loading more projections…</span>
          )}
        </p>
      </div>

      {isError ? (
        <div className="text-rose-400 text-sm bg-rose-400/10 border border-rose-400/30 rounded-xl p-4">
          Failed to load today&apos;s slate. Is the API running?
        </div>
      ) : loading ? (
        <LoadingState />
      ) : !hasContent || picks.length === 0 ? (
        <p className="text-zinc-500 text-sm bg-[#0e1015] border border-white/10 rounded-xl p-6">
          No projections yet — probable pitchers or lineups aren&apos;t confirmed for today&apos;s
          games. Check back closer to first pitch.
        </p>
      ) : noLeans ? (
        <div className="bg-[#0e1015] border border-white/10 rounded-xl px-6 py-10 text-center">
          <h2 className="text-lg font-semibold text-zinc-100">Not a great slate</h2>
          <p className="mt-2 text-sm text-zinc-400 max-w-md mx-auto">
            Nothing clears our conviction bar today — no hitter stands out enough to call a
            favorite. We&apos;d rather say nothing than force a weak pick. Check back closer to
            first pitch as lineups firm up.
          </p>
        </div>
      ) : (
        <div className="space-y-6">
          <BetOfTheDay selection={betOfDay} />
          <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
            <MarketCard
              title="Most Likely Hit"
              blurb="Best P(H≥1) lean across the slate."
              selection={hitSel}
            />
            <MarketCard
              title="Top Home Run"
              blurb="Best P(HR) lean — matchup, park, and weather driven."
              selection={hrSel}
            />
            <MarketCard
              title="Best Total Bases"
              blurb="Highest projected total bases (model only — no posted line)."
              selection={tbSel}
            />
          </div>
        </div>
      )}

      <p className="mt-6 text-[11px] text-zinc-600">
        Prop prices shown are {bookLabel('betrivers')} (best available where it has no line). Edges
        are model probability vs the book&apos;s implied price.
      </p>
    </main>
  )
}
