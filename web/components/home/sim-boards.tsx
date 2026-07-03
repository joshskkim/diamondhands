'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { mostLikelyQueryOptions, todayGamesQueryOptions } from '@/lib/api'
import type { MostLikely } from '@/lib/types'
import { cn } from '@/lib/utils'
import {
  liveNrfiOutcome,
  liveTotalOutcome,
  nrfiOutcome,
  runLineOutcome,
  totalLeanOutcome,
  type PickOutcome,
} from '@/lib/picks'
import { BoardCard, Rank } from './pick-boards'
import { OutcomeBadge } from './outcome-badge'

// Final scores + first-inning runs (and live state) per game, for live ✓/✗ grading.
interface GameResult {
  finalHome: number | null
  finalAway: number | null
  home1st: number | null
  away1st: number | null
  homeAbbr: string
  awayAbbr: string
  liveTotal: number | null
  liveHome: number | null
  liveAway: number | null
  liveCurrentInning: number | null
  isFinal: boolean
  isLive: boolean
}

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

// Concise by design: top N leans per market, strongest first. The full slate
// lives on the game pages — this is the skim view.
const N = 5

function pct(v: number | null | undefined) {
  if (v == null) return '—'
  return (v * 100).toFixed(0) + '%'
}

function signed(v: number | null | undefined, digits = 1) {
  if (v == null) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(digits)
}

function Matchup({ gameId, label }: { gameId: number; label: string }) {
  return (
    <Link
      href={`/mlb/games/${gameId}`}
      className="font-mono text-[13px] text-zinc-200 hover:text-white transition-colors"
    >
      {label}
    </Link>
  )
}

function Empty() {
  return <div className="px-4 py-6 text-xs text-zinc-600">Nothing simulated for this slate yet.</div>
}

// The matchup link with a ✓/✗ badge alongside once the lean is graded.
function RowMatchup({
  gameId,
  label,
  outcome,
}: {
  gameId: number
  label: string
  outcome?: PickOutcome
}) {
  return (
    <div className="flex items-center gap-1.5">
      <Matchup gameId={gameId} label={label} />
      {outcome && <OutcomeBadge outcome={outcome} iconOnly />}
    </div>
  )
}

function TotalsCard({ data, games }: { data: MostLikely['totals']; games: Map<number, GameResult> }) {
  const rows = [...data]
    .sort((a, b) => Math.abs(b.edge ?? 0) - Math.abs(a.edge ?? 0))
    .slice(0, N)
  return (
    <BoardCard
      title="Totals vs Line"
      blurb="Sim expected total vs the consensus book line — strongest leans first"
    >
      {rows.length === 0 && <Empty />}
      {rows.map((t, i) => {
        const g = games.get(t.gameId)
        const lean = t.lean === 'over' || t.lean === 'under' ? t.lean : null
        const outcome =
          totalLeanOutcome(t.lean, t.bookLine, g?.finalHome ?? null, g?.finalAway ?? null) ??
          liveTotalOutcome(lean, t.bookLine, g?.liveTotal, g?.isFinal ?? false)
        return (
        <div key={t.gameId} className="flex items-center gap-3 px-4 py-2 hover:bg-white/[0.03] transition-colors">
          <Rank n={i + 1} />
          <div className="min-w-0 flex-1">
            <RowMatchup gameId={t.gameId} label={t.matchup} outcome={outcome} />
            <div className="text-[11px] text-zinc-500 mt-0.5">
              sim <span className="text-zinc-300 font-mono">{t.simTotal.toFixed(1)}</span>
              {t.bookLine != null && (
                <> · line <span className="text-zinc-400 font-mono">{t.bookLine.toFixed(1)}</span></>
              )}
            </div>
          </div>
          <div className="text-right shrink-0 w-14">
            <div className={microLabel}>Edge</div>
            <div
              className={cn(
                'text-[13px] font-mono tabular-nums',
                t.edge == null ? 'text-zinc-600' : t.edge > 0 ? 'text-emerald-400' : t.edge < 0 ? 'text-rose-400' : 'text-zinc-400',
              )}
            >
              {t.edge == null ? '—' : signed(t.edge)}
            </div>
          </div>
          <div className="text-right shrink-0 w-12">
            <div className={microLabel}>Over</div>
            <div className="text-[13px] font-mono tabular-nums text-zinc-300">{pct(t.pOver)}</div>
          </div>
        </div>
        )
      })}
    </BoardCard>
  )
}

function RunLineCard({ data, games }: { data: MostLikely['runLine']; games: Map<number, GameResult> }) {
  const rows = data.slice(0, N)
  return (
    <BoardCard
      title="Run Line"
      blurb="Sim ±1.5 cover lean vs the de-vigged book price — best-edge side, strongest first"
    >
      {rows.length === 0 && <Empty />}
      {rows.map((r, i) => {
        const g = games.get(r.gameId)
        const outcome = g
          ? runLineOutcome(r.side === 'home', r.line, g.finalHome, g.finalAway) ??
            (g.isLive ? 'live' : undefined)
          : undefined
        const spread = r.line > 0 ? `+${r.line}` : `${r.line}`
        return (
        <div key={r.gameId} className="flex items-center gap-3 px-4 py-2 hover:bg-white/[0.03] transition-colors">
          <Rank n={i + 1} />
          <div className="min-w-0 flex-1">
            <RowMatchup gameId={r.gameId} label={r.matchup} outcome={outcome} />
            <div className="text-[11px] text-zinc-500 mt-0.5">
              cover <span className="text-zinc-300 font-semibold">{r.team}</span> {spread}{' '}
              {pct(r.coverProb)}
            </div>
          </div>
          <div className="text-right shrink-0 w-12">
            <div className={microLabel}>Cover</div>
            <div className="text-[13px] font-mono tabular-nums text-zinc-300">{pct(r.coverProb)}</div>
          </div>
          <div className="text-right shrink-0 w-14">
            <div className={microLabel}>Edge</div>
            <div
              className={cn(
                'text-[13px] font-mono tabular-nums',
                r.edge == null ? 'text-zinc-600' : r.edge > 0 ? 'text-emerald-400' : 'text-rose-400',
              )}
            >
              {r.edge == null ? '—' : signed(r.edge, 2)}
            </div>
          </div>
        </div>
        )
      })}
    </BoardCard>
  )
}

function NrfiCard({ data, games }: { data: MostLikely['nrfi']; games: Map<number, GameResult> }) {
  const rows = data.slice(0, N)
  return (
    <BoardCard title="NRFI / YRFI" blurb="First-inning run lean by simulated confidence">
      {rows.length === 0 && <Empty />}
      {rows.map((n, i) => {
        const g = games.get(n.gameId)
        const outcome =
          nrfiOutcome(n.lean, g?.home1st ?? null, g?.away1st ?? null) ??
          liveNrfiOutcome(n.lean, g?.liveHome, g?.liveAway, g?.liveCurrentInning, g?.isFinal ?? false)
        return (
        <div key={n.gameId} className="flex items-center gap-3 px-4 py-2 hover:bg-white/[0.03] transition-colors">
          <Rank n={i + 1} />
          <div className="min-w-0 flex-1">
            <RowMatchup gameId={n.gameId} label={n.matchup} outcome={outcome} />
            <div className="text-[11px] text-zinc-500 mt-0.5">
              YRFI {pct(n.pYrfi)} · NRFI {pct(n.pNrfi)}
            </div>
          </div>
          <div className="text-right shrink-0 w-16">
            <div className={microLabel}>Lean</div>
            <div
              className={cn(
                'text-[13px] font-semibold tabular-nums',
                n.lean === 'NRFI' ? 'text-sky-400' : 'text-amber-400',
              )}
            >
              {n.lean} {pct(n.leanProb)}
            </div>
          </div>
        </div>
        )
      })}
    </BoardCard>
  )
}

function SimBoardsSkeleton() {
  return (
    <section className="mb-10">
      <h2 className="text-sm font-semibold tracking-tight text-zinc-100 mb-1">Sim Signals</h2>
      <p className="text-zinc-500 text-xs mb-3">
        Monte-Carlo game-simulator leans — totals vs the book line, the ±1.5 run line, and
        first-inning runs. Top {N} per market.
      </p>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        {Array.from({ length: 3 }).map((_, i) => (
          <div
            key={i}
            className="rounded-xl border border-white/10 bg-[#0e1015] p-4 space-y-2.5"
          >
            <div className="h-4 w-32 animate-pulse rounded bg-white/5" />
            <div className="h-3 w-48 animate-pulse rounded bg-white/5" />
            {Array.from({ length: N }).map((_, r) => (
              <div key={r} className="h-7 w-full animate-pulse rounded bg-white/5" />
            ))}
          </div>
        ))}
      </div>
    </section>
  )
}

/**
 * The game-sim leans that used to live on the standalone Most Likely page,
 * condensed into one section of Today's Board. Renders nothing until the sim
 * has produced output for the slate.
 */
export function SimBoards() {
  const { data, isPending } = useQuery(mostLikelyQueryOptions())
  // Reuse the home page's today-games query (final scores + first-inning runs) to grade
  // each lean ✓/✗ once its game is final — same source the projected-favorites badge uses.
  const { data: games } = useQuery(todayGamesQueryOptions())
  const gamesById = new Map<number, GameResult>(
    (games ?? []).map((g) => {
      const isFinal = g.finalHomeScore != null && g.finalAwayScore != null
      const liveTotal =
        g.liveHomeScore != null && g.liveAwayScore != null
          ? g.liveHomeScore + g.liveAwayScore
          : null
      return [
        g.gameId,
        {
          finalHome: g.finalHomeScore,
          finalAway: g.finalAwayScore,
          home1st: g.finalHomeFirstInningRuns,
          away1st: g.finalAwayFirstInningRuns,
          homeAbbr: g.home.abbr,
          awayAbbr: g.away.abbr,
          liveTotal,
          liveHome: g.liveHomeScore,
          liveAway: g.liveAwayScore,
          liveCurrentInning: g.liveCurrentInning,
          isFinal,
          isLive: !isFinal && (g.status === 'Live' || liveTotal != null),
        },
      ]
    }),
  )

  // While the sim loads, hold the section's shape with skeletons so the page
  // below doesn't jump when the boards arrive.
  if (isPending) return <SimBoardsSkeleton />
  if (!data) return null
  if (data.totals.length === 0 && data.runLine.length === 0 && data.nrfi.length === 0) return null

  return (
    <section className="mb-10">
      <h2 className="text-sm font-semibold tracking-tight text-zinc-100 mb-1">
        Sim Signals
      </h2>
      <p className="text-zinc-500 text-xs mb-3">
        Monte-Carlo game-simulator leans — totals vs the book line, the ±1.5 run line, and
        first-inning runs. Top {N} per market.
      </p>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <TotalsCard data={data.totals} games={gamesById} />
        <RunLineCard data={data.runLine} games={gamesById} />
        <NrfiCard data={data.nrfi} games={gamesById} />
      </div>
    </section>
  )
}
