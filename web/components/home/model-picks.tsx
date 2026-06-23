'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Flame, Ticket } from 'lucide-react'
import {
  bestPlaysQueryOptions,
  hitRatesQueryOptions,
  mostLikelyQueryOptions,
  playerResultsQueryOptions,
  todayGamesQueryOptions,
} from '@/lib/api'
import type { BestPlay, HitRate, MostLikely, TodayGame } from '@/lib/types'
import { cn } from '@/lib/utils'
import { bookLabel, formatAmerican } from '@/lib/odds'
import { modelPlayOutcome, pickTitle, type PickOutcome } from '@/lib/picks'
import { OutcomeBadge } from './outcome-badge'
import { WhyDisclosure } from './why-disclosure'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

// ── the bar a line must clear (KEEP IN SYNC with ingester/commands/picks.py) ──
// A line only makes the board when the model and the price BOTH say yes:
//   · de-vigged edge (model − fair) of at least MIN_EDGE
//   · expected value at the best price of at least MIN_EV
//   · model probability ≥ MIN_MODEL_PROB — below that, a couple points of model
//     error flips the math, so longshots must show an outsized LONGSHOT_EDGE
//   · edge ≤ MAX_EDGE — when model and market disagree by more, the smart read
//     is model error or a stale line, not free money (tightened 0.25 → 0.15
//     after the 0/3 day, whose misses were all 18–21pt "edges")
//   · a totals lean is vetoed if the Monte-Carlo game sim lands on the other side
//   · pitcher props are excluded — backtests show no model edge there; the 'hit'
//     market is excluded too (H≥1 has near-zero skill signal) pending the
//     scoring loop's band calibration
//   · an HR prop must not contradict the hit-rate traffic light (season clear
//     rate, n ≥ 15): no overs on red, no unders on green
// One pick per game, MAX_PICKS at most. When nothing qualifies, we say so.
//
// A pick reads "Strong" (vs "Lean") on conviction in the *value*, not on
// absolute likelihood: a meaningful absolute edge AND a meaningful proportional
// overlay (model ÷ fair). There is no absolute-probability floor — that floor
// used to quietly reserve Strong for totals (whose model prob hugs the coinflip
// line) and lock every longshot prop to Lean. The overlay rule is scale-free, so
// a 53% total and a 12% HR-over are judged on the same footing.
const MIN_EDGE = 0.04
const MAX_EDGE = 0.15
const MIN_EV = 0.05
const MIN_MODEL_PROB = 0.4
const LONGSHOT_EDGE = 0.08
const STRONG_EDGE = 0.06
const STRONG_OVERLAY = 1.15
const MAX_PICKS = 3
// The "Lotto of the Day" — one deliberate longshot, model 5–30% with big value (see
// docs/model-explained.md). It's surfaced as its own card, not in the value grid, so its very
// different hit rate doesn't read like a Lean. Same gates as the board, minus the prob floor.
const LOTTO_MIN_PROB = 0.05
const LOTTO_MAX_PROB = 0.3
const EXCLUDED_MARKETS = new Set(['pitcher_k', 'pitcher_outs', 'hit'])
const HIT_RATE_VETO_MIN_N = 15
// Per-market veto bands: [no OVER below, no UNDER above]. Market-specific because
// clear-rate scales differ wildly — hit bands applied to HR would veto every
// slugger alive. Markets absent here never veto.
const HIT_RATE_VETO_BANDS: Record<string, [number, number]> = {
  hit: [0.45, 0.65],
  hr: [0.08, 0.5],
}

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

// A prop that contradicts the player's season clear rate (the hit-rate traffic
// light) needs more than a model-market gap. Bands are per market.
function hitRateVeto(p: BestPlay, hitRates: Map<string, HitRate> | undefined): boolean {
  if (!hitRates || p.playerId == null) return false
  const band = HIT_RATE_VETO_BANDS[p.market]
  if (!band) return false
  const hr = hitRates.get(`${p.playerId}:${p.market}`)
  if (!hr || hr.season == null || hr.nSeason < HIT_RATE_VETO_MIN_N) return false
  if (p.side === 'over') return hr.season < band[0]
  if (p.side === 'under') return hr.season > band[1]
  return false
}

// The "Why" lines for a pick — shared by the value grid and the lotto card so wording stays
// identical. fairProb is asserted non-null because every caller guards it before calling.
function buildReasons(p: BestPlay, edge: number, corroboration: string | null): string[] {
  const reasons = [
    `Model probability ${pct(p.modelProb)} against a de-vigged market ${pct(p.fairProb!)} — a ${(edge * 100).toFixed(1)}-point edge after stripping the book's margin from both sides.`,
    `${signedPct(p.evPct)} expected value per unit at the best available price, ${formatAmerican(p.priceAmerican)} (${bookLabel(p.bestBook)}).`,
  ]
  if (p.modelProb < 0.5) {
    reasons.push(
      'A longshot by design — it makes the board because the price overpays the model probability, not because it should usually hit.',
    )
  }
  if (corroboration) reasons.push(corroboration)
  return reasons
}

function buildPicks(
  plays: BestPlay[],
  sim: MostLikely | undefined,
  hitRates: Map<string, HitRate> | undefined,
): ModelPick[] {
  const candidates: ModelPick[] = []

  for (const p of plays) {
    if (EXCLUDED_MARKETS.has(p.market)) continue
    if (p.fairProb == null) continue // one-sided price — can't de-vig, can't trust
    const edge = p.modelProb - p.fairProb
    if (edge < MIN_EDGE || edge > MAX_EDGE) continue
    if (p.evPct < MIN_EV) continue
    if (p.modelProb < MIN_MODEL_PROB && edge < LONGSHOT_EDGE) continue
    if (hitRateVeto(p, hitRates)) continue

    const totals = simTotalsCheck(p, sim)
    if (totals.veto) continue
    const corroboration = totals.note ?? simPropNote(p, sim)

    candidates.push({
      play: p,
      edge,
      // fairProb is non-null here (guarded above), so the overlay is safe.
      strong: edge >= STRONG_EDGE && p.modelProb / p.fairProb >= STRONG_OVERLAY,
      // Edge is the primary signal; EV breaks ties toward better prices, and
      // independent sim agreement nudges a pick up the board.
      score: edge + 0.5 * p.evPct + (corroboration ? 0.02 : 0),
      reasons: buildReasons(p, edge, corroboration),
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

// The single best longshot for the "Lotto of the Day" card. Same gates as the board (value,
// price, sim & traffic-light vetoes) but the model probability must sit in the lotto band — these
// are the plays the grid's MIN_MODEL_PROB floor would otherwise reserve for a quiet "Lean".
function pickLotto(
  plays: BestPlay[],
  sim: MostLikely | undefined,
  hitRates: Map<string, HitRate> | undefined,
): ModelPick | null {
  let best: ModelPick | null = null

  for (const p of plays) {
    if (EXCLUDED_MARKETS.has(p.market)) continue
    if (p.fairProb == null) continue
    if (p.modelProb < LOTTO_MIN_PROB || p.modelProb > LOTTO_MAX_PROB) continue
    const edge = p.modelProb - p.fairProb
    if (edge < LONGSHOT_EDGE || edge > MAX_EDGE) continue // longshots need the bigger edge
    if (p.evPct < MIN_EV) continue
    if (hitRateVeto(p, hitRates)) continue

    const totals = simTotalsCheck(p, sim)
    if (totals.veto) continue
    const corroboration = totals.note ?? simPropNote(p, sim)

    const score = edge + 0.5 * p.evPct + (corroboration ? 0.02 : 0)
    if (best == null || score > best.score) {
      best = { play: p, edge, score, strong: false, reasons: buildReasons(p, edge, corroboration) }
    }
  }
  return best
}

// ── presentation ──────────────────────────────────────────────────────────────

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

function PickCard({
  pick,
  rank,
  outcome,
}: {
  pick: ModelPick
  rank: number
  outcome?: PickOutcome
}) {
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
        {outcome && <OutcomeBadge outcome={outcome} />}
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

      <WhyDisclosure reasons={pick.reasons} />
    </div>
  )
}

function LottoCard({ pick, outcome }: { pick: ModelPick; outcome?: PickOutcome }) {
  const p = pick.play
  return (
    <div className="rounded-xl border border-amber-400/30 bg-gradient-to-br from-amber-500/10 to-[#0e1015] px-5 py-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <Ticket className="h-4 w-4 text-amber-300" aria-hidden="true" />
        <span className="text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border text-amber-200 border-amber-400/40 bg-amber-500/10">
          Lotto
        </span>
        {outcome && <OutcomeBadge outcome={outcome} />}
        <Link
          href={`/mlb/games/${p.gameId}`}
          className="ml-auto font-mono text-xs text-zinc-500 hover:text-amber-300 transition-colors"
        >
          {p.matchup}
        </Link>
      </div>

      <div className="flex items-baseline justify-between gap-3">
        {p.playerId ? (
          <Link
            href={`/mlb/players/${p.playerId}`}
            className="text-base font-bold tracking-tight text-zinc-100 hover:text-amber-200 transition-colors"
          >
            {pickTitle(p)}
          </Link>
        ) : (
          <span className="text-base font-bold tracking-tight text-zinc-100">{pickTitle(p)}</span>
        )}
        <span className="shrink-0 font-mono tabular-nums text-sm text-amber-200">
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

      <WhyDisclosure reasons={pick.reasons} />
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
  const { data: hitRateData } = useQuery(hitRatesQueryOptions())
  // Grade live as games finish — final scores from today-games, HR from player results —
  // the same source the projected-favorites badge uses, so ✓/✗ lands same-day.
  const { data: games } = useQuery(todayGamesQueryOptions())
  const { data: results } = useQuery(playerResultsQueryOptions())

  const rows = plays ?? []
  const hitRates = new Map<string, HitRate>(
    (hitRateData ?? []).map((h) => [`${h.playerId}:${h.market}`, h]),
  )
  const gamesById = new Map<number, TodayGame>((games ?? []).map((g) => [g.gameId, g]))
  const hrByKey = new Map<string, number | null>(
    (results?.batters ?? []).map((b) => [`${b.playerId}:${b.gameId}`, b.homeRuns]),
  )
  // Pull the lotto first so it shows only on its own card, then build the value grid from the rest
  // (a promoted longshot never reads as both a "Lotto" and a quiet "Lean").
  const lotto = pickLotto(rows, sim, hitRates)
  const gridRows = lotto ? rows.filter((p) => p !== lotto.play) : rows
  const picks = buildPicks(gridRows, sim, hitRates)

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
            <PickCard
              key={`${pick.play.gameId}-${pick.play.market}-${pick.play.selection}`}
              pick={pick}
              rank={i + 1}
              outcome={modelPlayOutcome(pick.play, gamesById.get(pick.play.gameId), hrByKey)}
            />
          ))}
        </div>
      )}

      {!isPending && !isError && lotto && (
        <div className="mt-6">
          <div className="mb-2 flex items-baseline gap-2">
            <h3 className="text-sm font-semibold tracking-tight text-amber-200">Lotto of the Day</h3>
            <span className="text-xs text-zinc-500">— one deliberate longshot, big payout</span>
          </div>
          <div className="lg:max-w-xl">
            <LottoCard
              pick={lotto}
              outcome={modelPlayOutcome(lotto.play, gamesById.get(lotto.play.gameId), hrByKey)}
            />
          </div>
        </div>
      )}
    </section>
  )
}
