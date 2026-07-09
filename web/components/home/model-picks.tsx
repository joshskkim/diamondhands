'use client'

import Link from 'next/link'
import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Flame } from 'lucide-react'
import {
  modelPicksQueryOptions,
  mostLikelyQueryOptions,
  playerResultsQueryOptions,
  tailPick,
  todayGamesQueryOptions,
} from '@/lib/api'
import type { ModelPickResult, MostLikely, TodayGame } from '@/lib/types'
import { cn } from '@/lib/utils'
import { pct, signedPct } from '@/lib/format'
import { bookLabel, formatAmerican } from '@/lib/odds'
import { modelPlayOutcome, pickOutcome, pickTitle, type PickOutcome } from '@/lib/picks'
import { useAuth } from '@/components/auth-provider'
import { microLabel, Skeleton } from '@/components/ui/primitives'
import { OutcomeBadge } from './outcome-badge'
import { LivePickTracker } from './live-tracker'
import { WhyDisclosure } from './why-disclosure'

// ── the board IS the record ───────────────────────────────────────────────────
// This component renders the picks the ingester's record-picks cron locked into
// model_picks (GET /api/model-picks) — it no longer computes its own picks. The
// bar (edge/EV floors, market exclusions, vetoes, the 3-per-slate budget) lives in
// ONE place: ingester/ingester/commands/picks.py. Picks lock at morning prices;
// the only thing that moves one afterwards is a lineup change that breaks its
// case (bump_reason='lineup'), and those rows stay visible below, still graded.

// The sim can't veto a locked pick (the bar already applied it at lock time);
// when it independently agrees, that agreement is still worth explaining.
function simNote(p: ModelPickResult, sim: MostLikely | undefined): string | null {
  if (!sim) return null
  if (p.market === 'total' && p.line != null) {
    const t = sim.totals.find((x) => x.gameId === p.gameId)
    if (!t) return null
    const agrees = p.side === 'over' ? t.simTotal > p.line : t.simTotal < p.line
    if (!agrees) return null
    return `The Monte-Carlo game sim independently lands at ${t.simTotal.toFixed(1)} runs against the ${p.line} line, agreeing with the ${p.side}.`
  }
  if (p.playerId != null && p.side === 'over') {
    const list =
      p.market === 'hit' ? sim.props.hits : p.market === 'hr' ? sim.props.homeRuns : null
    if (!list) return null
    const idx = list.findIndex((r) => r.playerId === p.playerId)
    if (idx === -1) return null
    return `${p.playerName} also ranks #${idx + 1} on the game sim's ${
      p.market === 'hit' ? 'hit' : 'home-run'
    } leaderboard today.`
  }
  return null
}

// The "Why" lines for a recorded pick, rebuilt from its locked numbers.
function buildReasons(p: ModelPickResult, corroboration: string | null): string[] {
  const reasons = [
    `Model probability ${pct(p.modelProb)} against a de-vigged market ${pct(p.fairProb)} — a ${(p.edge * 100).toFixed(1)}-point edge after stripping the book's margin from both sides, locked at the price the pick was recorded at.`,
    `${signedPct(p.evPct)} expected value per unit at ${formatAmerican(p.priceAmerican)} (${bookLabel(p.book ?? undefined)}).`,
  ]
  if (p.modelProb < 0.5) {
    reasons.push(
      'A longshot by design — it makes the board because the price overpays the model probability, not because it should usually hit.',
    )
  }
  if (corroboration) reasons.push(corroboration)
  if (p.debateVerdict === 'bet' || p.debateVerdict === 'lean') {
    const conf = p.debateConfidence != null ? ` (${Math.round(p.debateConfidence * 100)}% confidence)` : ''
    reasons.push(
      `The Analyst's bull-vs-skeptic debate endorsed this${conf}${p.debateRationale ? `: ${p.debateRationale}` : '.'}`,
    )
  }
  return reasons
}

/** The judge's endorsement chip — shown on a pick the Analyst gate promoted (bet/lean). */
function AnalystChip({ verdict, confidence }: { verdict?: string | null; confidence?: number | null }) {
  if (verdict !== 'bet' && verdict !== 'lean') return null
  return (
    <span
      title="The Analyst's bull/skeptic/judge debate endorsed this pick"
      className="text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border text-violet-300 border-violet-400/40 bg-violet-500/10"
    >
      Analyst {confidence != null ? `${Math.round(confidence * 100)}%` : verdict}
    </span>
  )
}

/** Tail a pick into your personal Tracker (server computes the Kelly stake). Signed-in only. */
function TailButton({ p }: { p: ModelPickResult }) {
  const { user } = useAuth()
  const [state, setState] = useState<'idle' | 'saving' | 'done' | 'error'>('idle')
  const [msg, setMsg] = useState<string | null>(null)
  if (!user) return null

  async function onTail() {
    setState('saving')
    try {
      const res = await tailPick({
        gameId: p.gameId, market: p.market, side: p.side, line: p.line,
        playerId: p.playerId, playerName: p.playerName, priceAmerican: p.priceAmerican,
        book: p.book, modelProb: p.modelProb, fairProb: p.fairProb,
        confidence: p.debateConfidence ?? null,
      })
      setMsg(res.message)
      setState('done')
    } catch {
      setMsg('Could not tail that.')
      setState('error')
    }
  }

  return (
    <div className="flex items-center gap-2">
      <button
        type="button"
        onClick={onTail}
        disabled={state === 'saving' || state === 'done'}
        className="rounded-md border border-cyan-400/40 bg-cyan-500/10 px-2.5 py-1 text-xs font-medium text-cyan-300 transition-colors hover:bg-cyan-500/20 disabled:opacity-60"
      >
        {state === 'done' ? 'Tailed ✓' : state === 'saving' ? 'Tailing…' : 'Tail'}
      </button>
      {msg && (
        <span className={cn('text-[11px]', state === 'error' ? 'text-rose-400' : 'text-zinc-400')}>{msg}</span>
      )}
    </div>
  )
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
  reasons,
  outcome,
  game,
}: {
  pick: ModelPickResult
  rank: number
  reasons: string[]
  outcome?: PickOutcome
  game?: TodayGame
}) {
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
        <AnalystChip verdict={pick.debateVerdict} confidence={pick.debateConfidence} />
        {outcome && <OutcomeBadge outcome={outcome} />}
        <Link
          href={`/mlb/games/${pick.gameId}`}
          className="ml-auto font-mono text-xs text-zinc-500 hover:text-cyan-400 transition-colors"
        >
          {pick.matchup}
        </Link>
      </div>

      <div className="flex items-baseline justify-between gap-3">
        {pick.playerId ? (
          <Link
            href={`/mlb/players/${pick.playerId}`}
            className="text-base font-bold tracking-tight text-zinc-100 hover:text-cyan-300 transition-colors"
          >
            {pickTitle(pick)}
          </Link>
        ) : (
          <span className="text-base font-bold tracking-tight text-zinc-100">
            {pickTitle(pick)}
          </span>
        )}
        <span className="shrink-0 font-mono tabular-nums text-sm text-cyan-300">
          {formatAmerican(pick.priceAmerican)}{' '}
          <span className="text-zinc-500 text-xs">{bookLabel(pick.book ?? undefined)}</span>
        </span>
      </div>

      <div className="grid grid-cols-4 gap-2">
        <Stat label="Model" value={pct(pick.modelProb)} className="text-zinc-200" />
        <Stat label="Fair" value={pct(pick.fairProb)} className="text-zinc-400" />
        <Stat label="Edge" value={signedPct(pick.edge)} className="text-emerald-400" />
        <Stat label="EV" value={signedPct(pick.evPct)} className="text-emerald-300" />
      </div>

      <LivePickTracker game={game} market={pick.market} side={pick.side} line={pick.line} outcome={outcome} />

      <WhyDisclosure reasons={reasons} />
      <TailButton p={pick} />
    </div>
  )
}

function NoPicksCard() {
  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl px-6 py-8 text-center">
      <h3 className="text-base font-semibold text-zinc-100">No picks today (yet)</h3>
      <p className="mt-2 text-sm text-zinc-400 max-w-lg mx-auto">
        Picks lock at morning prices, at most 3 per slate, and only when a line clears the
        bar: a 6-point edge over the de-vigged market, +5% expected value at the best
        price, and no disagreement from the game sim. Nothing has cleared it so far —
        we&apos;d rather pass than force a play. Remaining slots can still fill as lineups
        post.
      </p>
    </div>
  )
}

// ── earlier picks (honest history) ──────────────────────────────────────────────
// A pick that left the board stays on the record, locked at the line it was shown at,
// still graded — the board never quietly rewrites its own history. bump_reason says
// why it left: 'lineup' (the lineup changed and the pick no longer cleared the bar at
// its locked terms) or legacy 'displaced' (pre-budget churn).

// ET clock time a pick first hit the board, e.g. "1:15 PM" (the slate's timezone).
function shownClock(iso: string | null): string | null {
  if (!iso) return null
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return null
  return new Intl.DateTimeFormat('en-US', {
    timeZone: 'America/New_York',
    hour: 'numeric',
    minute: '2-digit',
  }).format(d)
}

function bumpCopy(reason: string | null): string {
  return reason === 'lineup'
    ? 're-evaluated after a lineup change'
    : 'replaced by a later pick'
}

function EarlierPickRow({ pick, outcome }: { pick: ModelPickResult; outcome?: PickOutcome }) {
  const shown = shownClock(pick.firstShownAt)
  return (
    <div className="flex items-center gap-3 rounded-lg border border-white/10 bg-[#0e1015] px-4 py-2.5">
      {outcome && <OutcomeBadge outcome={outcome} />}
      <div className="min-w-0 flex-1">
        <div className="truncate text-sm text-zinc-300">
          {pick.playerId ? (
            <Link
              href={`/mlb/players/${pick.playerId}`}
              className="transition-colors hover:text-cyan-300"
            >
              {pickTitle(pick)}
            </Link>
          ) : (
            pickTitle(pick)
          )}
        </div>
        <div className="text-xs text-zinc-500">
          {formatAmerican(pick.priceAmerican)} {bookLabel(pick.book ?? undefined)}
          {shown != null && <> · shown {shown}</>} · {bumpCopy(pick.bumpReason)}
        </div>
      </div>
      <Link
        href={`/mlb/games/${pick.gameId}`}
        className="shrink-0 font-mono text-xs text-zinc-500 transition-colors hover:text-cyan-400"
      >
        {pick.matchup}
      </Link>
    </div>
  )
}

function EarlierPicks({
  picks,
  gamesById,
  hrByKey,
}: {
  picks: ModelPickResult[]
  gamesById: Map<number, TodayGame>
  hrByKey: Map<string, number | null>
}) {
  if (picks.length === 0) return null
  return (
    <div className="mt-4">
      <h3 className={cn(microLabel, 'mb-2 normal-case tracking-normal text-zinc-400')}>
        Earlier today — picks taken off the board (kept on the record, still graded)
      </h3>
      <div className="grid gap-2">
        {picks.map((p) => (
          <EarlierPickRow
            key={`${p.gameId}-${p.market}-${p.side}-${p.playerId ?? ''}`}
            pick={p}
            outcome={
              p.scored ? pickOutcome(p) : modelPlayOutcome(p, gamesById.get(p.gameId), hrByKey)
            }
          />
        ))}
      </div>
    </div>
  )
}

export function ModelPicks() {
  // The recorded snapshot IS the board (see the header comment).
  const { data: recorded, isPending, isError } = useQuery(modelPicksQueryOptions())
  const { data: sim } = useQuery(mostLikelyQueryOptions())
  // Grade live as games finish — final scores from today-games, HR from player results —
  // the same source the projected-favorites badge uses, so ✓/✗ lands same-day.
  const { data: games } = useQuery(todayGamesQueryOptions())
  const { data: results } = useQuery(playerResultsQueryOptions())

  const gamesById = new Map<number, TodayGame>((games ?? []).map((g) => [g.gameId, g]))
  const hrByKey = new Map<string, number | null>(
    (results?.batters ?? []).map((b) => [`${b.playerId}:${b.gameId}`, b.homeRuns]),
  )

  const rows = recorded ?? []
  // The API orders active-first by rank; keep that order for the cards.
  const picks = rows.filter((p) => p.active)
  const earlier = rows.filter((p) => !p.active && p.firstShownAt != null)

  let picksContent
  if (isPending) {
    picksContent = (
      <div className="grid gap-4 lg:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <Skeleton key={i} className="h-44 w-full rounded-xl" />
        ))}
      </div>
    )
  } else if (isError) {
    picksContent = (
      <p className="text-sm text-zinc-500 bg-[#0e1015] border border-white/10 rounded-xl px-5 py-4">
        Couldn&apos;t load the recorded picks right now.
      </p>
    )
  } else if (picks.length === 0) {
    picksContent = <NoPicksCard />
  } else {
    picksContent = (
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
            key={`${pick.gameId}-${pick.market}-${pick.side}-${pick.playerId ?? ''}`}
            pick={pick}
            rank={i + 1}
            reasons={buildReasons(pick, simNote(pick, sim))}
            outcome={modelPlayOutcome(pick, gamesById.get(pick.gameId), hrByKey)}
            game={gamesById.get(pick.gameId)}
          />
        ))}
      </div>
    )
  }

  return (
    <section className="mb-10">
      <div className="mb-3">
        <h2 className="text-sm font-semibold tracking-tight text-zinc-100 flex items-center gap-1.5">
          <Flame className="h-4 w-4 text-cyan-300" aria-hidden="true" />
          Model&apos;s Picks
        </h2>
        <p className="text-xs text-zinc-500 mt-0.5">
          At most 3 per day, locked at morning prices — the lines where the model&apos;s
          probability beats the de-vigged market by enough to matter, with the reasoning.
        </p>
      </div>

      {picksContent}

      <EarlierPicks picks={earlier} gamesById={gamesById} hrByKey={hrByKey} />
    </section>
  )
}
