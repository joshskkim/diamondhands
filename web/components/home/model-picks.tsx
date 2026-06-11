'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Flame } from 'lucide-react'
import { bestPlaysQueryOptions, mostLikelyQueryOptions } from '@/lib/api'
import type { BestPlay, MostLikely } from '@/lib/types'
import { cn } from '@/lib/utils'
import { bookLabel, formatAmerican, MARKET_LABEL, teamForSide } from '@/lib/odds'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

// ── the bar a line must clear ─────────────────────────────────────────────────
// A line only makes the board when the model and the price BOTH say yes:
//   · de-vigged edge (model − fair) of at least MIN_EDGE
//   · expected value at the best price of at least MIN_EV
//   · model probability ≥ MIN_MODEL_PROB — below that, a couple points of model
//     error flips the math, so longshots must show an outsized LONGSHOT_EDGE
//   · edge ≤ MAX_EDGE — when model and market disagree by 25+ points, the smart
//     read is model error or a stale line, not free money
//   · a totals lean is vetoed if the Monte-Carlo game sim lands on the other side
//   · pitcher props are excluded entirely — backtests show no model edge there
// One pick per game, MAX_PICKS at most. When nothing qualifies, we say so.
const MIN_EDGE = 0.04
const MAX_EDGE = 0.25
const MIN_EV = 0.05
const MIN_MODEL_PROB = 0.4
const LONGSHOT_EDGE = 0.08
const STRONG_EDGE = 0.06
const MAX_PICKS = 3
const EXCLUDED_MARKETS = new Set(['pitcher_k', 'pitcher_outs'])

interface ModelPick {
  play: BestPlay
  edge: number
  score: number
  strong: boolean
  reasons: string[]
}

function pct(v: number) {
  return (v * 100).toFixed(1) + '%'
}

function signedPct(v: number) {
  return (v > 0 ? '+' : '') + (v * 100).toFixed(1) + '%'
}

// Totals picks must agree with the game sim when it covers the game; when it
// does, that independent agreement becomes part of the explanation.
function simTotalsCheck(
  p: BestPlay,
  sim: MostLikely | undefined,
): { veto: boolean; note: string | null } {
  if (p.market !== 'total' || p.line == null || !sim) return { veto: false, note: null }
  const t = sim.totals.find((x) => x.gameId === p.gameId)
  if (!t) return { veto: false, note: null }
  const agrees = p.side === 'over' ? t.simTotal > p.line : t.simTotal < p.line
  if (!agrees) return { veto: true, note: null }
  return {
    veto: false,
    note: `The Monte-Carlo game sim independently lands at ${t.simTotal.toFixed(1)} runs against the ${p.line} line, agreeing with the ${p.side}.`,
  }
}

// Hit/HR overs get a corroboration note when the sim's own leaderboard agrees.
function simPropNote(p: BestPlay, sim: MostLikely | undefined): string | null {
  if (!sim || p.playerId == null || p.side !== 'over') return null
  const list =
    p.market === 'hit' ? sim.props.hits : p.market === 'hr' ? sim.props.homeRuns : null
  if (!list) return null
  const idx = list.findIndex((r) => r.playerId === p.playerId)
  if (idx === -1) return null
  return `${p.playerName} also ranks #${idx + 1} on the game sim's ${
    p.market === 'hit' ? 'hit' : 'home-run'
  } leaderboard today.`
}

function buildPicks(plays: BestPlay[], sim: MostLikely | undefined): ModelPick[] {
  const candidates: ModelPick[] = []

  for (const p of plays) {
    if (EXCLUDED_MARKETS.has(p.market)) continue
    if (p.fairProb == null) continue // one-sided price — can't de-vig, can't trust
    const edge = p.modelProb - p.fairProb
    if (edge < MIN_EDGE || edge > MAX_EDGE) continue
    if (p.evPct < MIN_EV) continue
    if (p.modelProb < MIN_MODEL_PROB && edge < LONGSHOT_EDGE) continue

    const totals = simTotalsCheck(p, sim)
    if (totals.veto) continue
    const corroboration = totals.note ?? simPropNote(p, sim)

    const reasons = [
      `Model probability ${pct(p.modelProb)} against a de-vigged market ${pct(p.fairProb)} — a ${(edge * 100).toFixed(1)}-point edge after stripping the book's margin from both sides.`,
      `${signedPct(p.evPct)} expected value per unit at the best available price, ${formatAmerican(p.priceAmerican)} (${bookLabel(p.bestBook)}).`,
    ]
    if (p.modelProb < 0.5) {
      reasons.push(
        'A longshot by design — it makes the board because the price overpays the model probability, not because it should usually hit.',
      )
    }
    if (corroboration) reasons.push(corroboration)

    candidates.push({
      play: p,
      edge,
      strong: edge >= STRONG_EDGE && p.modelProb >= 0.5,
      // Edge is the primary signal; EV breaks ties toward better prices, and
      // independent sim agreement nudges a pick up the board.
      score: edge + 0.5 * p.evPct + (corroboration ? 0.02 : 0),
      reasons,
    })
  }

  candidates.sort((a, b) => b.score - a.score)

  const picks: ModelPick[] = []
  const usedGames = new Set<number>()
  for (const c of candidates) {
    if (usedGames.has(c.play.gameId)) continue // one pick per game
    usedGames.add(c.play.gameId)
    picks.push(c)
    if (picks.length === MAX_PICKS) break
  }
  return picks
}

// ── presentation ──────────────────────────────────────────────────────────────

function pickTitle(p: BestPlay): string {
  const sideWord = p.side === 'over' ? 'Over' : p.side === 'under' ? 'Under' : null
  switch (p.market) {
    case 'moneyline':
      return `${teamForSide(p.matchup, p.side)} moneyline`
    case 'run_line':
      return `${teamForSide(p.matchup, p.side)} ${p.line != null && p.line > 0 ? `+${p.line}` : p.line} run line`
    case 'total':
      return `${sideWord} ${p.line} total runs`
    case 'hit':
      return `${p.playerName} ${sideWord?.toLowerCase()} ${p.line} hits`
    case 'hr':
      return `${p.playerName} ${sideWord?.toLowerCase()} ${p.line} home runs`
    default:
      return `${p.playerName ?? p.matchup} ${sideWord ?? p.side} ${p.line ?? ''} ${MARKET_LABEL[p.market] ?? p.market}`.trim()
  }
}

function Stat({
  label,
  value,
  className,
}: {
  label: string
  value: string
  className?: string
}) {
  return (
    <div>
      <div className={microLabel}>{label}</div>
      <div className={cn('text-[13px] font-mono tabular-nums', className)}>{value}</div>
    </div>
  )
}

function PickCard({ pick, rank }: { pick: ModelPick; rank: number }) {
  const p = pick.play
  return (
    <div
      className={cn(
        'rounded-xl border px-5 py-4 flex flex-col gap-3',
        rank === 1
          ? 'bg-gradient-to-br from-cyan-500/10 to-[#0e1015] border-cyan-400/30'
          : 'bg-[#0e1015] border-white/10',
      )}
    >
      <div className="flex items-center gap-2">
        <span className="font-mono text-xs text-zinc-500">#{rank}</span>
        <span
          className={cn(
            'text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border',
            pick.strong
              ? 'text-cyan-300 border-cyan-400/40 bg-cyan-500/10'
              : 'text-zinc-400 border-white/15 bg-white/5',
          )}
        >
          {pick.strong ? 'Strong' : 'Lean'}
        </span>
        <Link
          href={`/mlb/games/${p.gameId}`}
          className="ml-auto font-mono text-xs text-zinc-500 hover:text-cyan-400 transition-colors"
        >
          {p.matchup}
        </Link>
      </div>

      <div className="flex items-baseline justify-between gap-3">
        {p.playerId ? (
          <Link
            href={`/mlb/players/${p.playerId}`}
            className="text-base font-bold tracking-tight text-zinc-100 hover:text-cyan-300 transition-colors"
          >
            {pickTitle(p)}
          </Link>
        ) : (
          <span className="text-base font-bold tracking-tight text-zinc-100">
            {pickTitle(p)}
          </span>
        )}
        <span className="shrink-0 font-mono tabular-nums text-sm text-cyan-300">
          {formatAmerican(p.priceAmerican)}{' '}
          <span className="text-zinc-500 text-xs">{bookLabel(p.bestBook)}</span>
        </span>
      </div>

      <div className="grid grid-cols-4 gap-2">
        <Stat label="Model" value={pct(p.modelProb)} className="text-zinc-200" />
        <Stat label="Fair" value={p.fairProb == null ? '—' : pct(p.fairProb)} className="text-zinc-400" />
        <Stat label="Edge" value={signedPct(pick.edge)} className="text-emerald-400" />
        <Stat label="EV" value={signedPct(p.evPct)} className="text-emerald-300" />
      </div>

      <ul className="space-y-1.5 text-[13px] leading-relaxed text-zinc-400 list-disc pl-4 marker:text-zinc-600">
        {pick.reasons.map((r, i) => (
          <li key={i}>{r}</li>
        ))}
      </ul>
    </div>
  )
}

function PassCard({ surveyed }: { surveyed: number }) {
  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl px-6 py-8 text-center">
      <h3 className="text-base font-semibold text-zinc-100">No picks today</h3>
      <p className="mt-2 text-sm text-zinc-400 max-w-lg mx-auto">
        We scanned {surveyed} priced line{surveyed === 1 ? '' : 's'} and none cleared the bar:
        at least a {(MIN_EDGE * 100).toFixed(0)}-point edge over the de-vigged market,{' '}
        {signedPct(MIN_EV)} expected value at the best price, and no disagreement from the
        game sim. We&apos;d rather pass than force a play — check back as lines and lineups move.
      </p>
    </div>
  )
}

function NoOddsCard() {
  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl px-6 py-8 text-center">
      <h3 className="text-base font-semibold text-zinc-100">No priced lines yet</h3>
      <p className="mt-2 text-sm text-zinc-400 max-w-lg mx-auto">
        Sportsbook odds haven&apos;t loaded for today&apos;s slate, so there&apos;s nothing to
        evaluate against the model. Picks appear once odds are ingested.
      </p>
    </div>
  )
}

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={cn('animate-pulse bg-white/5 rounded', className)} />
}

export function ModelPicks() {
  const { data: plays, isPending, isError } = useQuery(bestPlaysQueryOptions(undefined, 100))
  const { data: sim } = useQuery(mostLikelyQueryOptions())

  const rows = plays ?? []
  const picks = buildPicks(rows, sim)

  return (
    <section className="mb-10">
      <div className="mb-3">
        <h2 className="text-sm font-semibold tracking-tight text-zinc-100 flex items-center gap-1.5">
          <Flame className="h-4 w-4 text-cyan-300" aria-hidden="true" />
          Model&apos;s Picks
        </h2>
        <p className="text-xs text-zinc-500 mt-0.5">
          Likelihood and value combined: the (at most) {MAX_PICKS} lines where the model&apos;s
          probability beats the de-vigged market by enough to matter — with the reasoning.
        </p>
      </div>

      {isPending ? (
        <div className="grid gap-4 lg:grid-cols-3">
          {Array.from({ length: 3 }).map((_, i) => (
            <Skeleton key={i} className="h-44 w-full rounded-xl" />
          ))}
        </div>
      ) : isError ? (
        <p className="text-sm text-zinc-500 bg-[#0e1015] border border-white/10 rounded-xl px-5 py-4">
          Couldn&apos;t load priced lines, so picks are unavailable right now.
        </p>
      ) : rows.length === 0 ? (
        <NoOddsCard />
      ) : picks.length === 0 ? (
        <PassCard surveyed={rows.length} />
      ) : (
        <div
          className={cn(
            'grid gap-4',
            picks.length === 1 && 'lg:max-w-xl',
            picks.length === 2 && 'lg:grid-cols-2',
            picks.length >= 3 && 'lg:grid-cols-3',
          )}
        >
          {picks.map((pick, i) => (
            <PickCard key={`${pick.play.gameId}-${pick.play.market}-${pick.play.selection}`} pick={pick} rank={i + 1} />
          ))}
        </div>
      )}
    </section>
  )
}
