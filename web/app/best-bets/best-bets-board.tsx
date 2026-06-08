'use client'

import Link from 'next/link'
import type { FlatBatterPick } from '@/lib/types'
import { usePicks } from '@/components/home/use-picks'
import { cn } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

const N = 8

function pct(v: number | null | undefined) {
  if (v == null) return '—'
  return (v * 100).toFixed(0) + '%'
}

function hand(pick: FlatBatterPick) {
  return pick.opposingPitcherThrows === 'L' ? 'LHP' : 'RHP'
}

// ── reserved sportsbook odds slot (MODEL EDGES ONLY for now) ──────────────────

function OddsSlot() {
  return (
    <div className="text-right shrink-0 w-16">
      {/* TODO: sportsbook odds — wire real best line / EV% here once props ship */}
      <div className={microLabel}>Odds</div>
      <div className="text-[11px] text-zinc-600 font-mono" title="Sportsbook odds coming soon">
        soon
      </div>
    </div>
  )
}

function Rank({ n }: { n: number }) {
  return (
    <span className="w-5 shrink-0 text-right font-mono tabular-nums text-xs text-zinc-600">
      {n}
    </span>
  )
}

// ── card shell ────────────────────────────────────────────────────────────────

function BoardCard({
  title,
  blurb,
  children,
}: {
  title: string
  blurb: string
  children: React.ReactNode
}) {
  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden flex flex-col">
      <div className="px-4 pt-4 pb-3 border-b border-white/10">
        <h2 className="font-semibold tracking-tight text-zinc-100 text-sm">{title}</h2>
        <p className="text-xs text-zinc-500 mt-0.5">{blurb}</p>
      </div>
      <div className="divide-y divide-white/5">{children}</div>
    </div>
  )
}

function EmptyBoard() {
  return <div className="px-4 py-6 text-xs text-zinc-600">No qualifying picks yet.</div>
}

// ── batter row ────────────────────────────────────────────────────────────────

function BetRow({
  rank,
  pick,
  value,
  valueClass,
  why,
}: {
  rank: number
  pick: FlatBatterPick
  value: string
  valueClass?: string
  why: string
}) {
  const b = pick.batter
  return (
    <div className="flex items-center gap-3 px-4 py-2 hover:bg-white/[0.03] transition-colors">
      <Rank n={rank} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <Link
            href={`/mlb/players/${b.player.id}`}
            className="font-medium text-zinc-100 hover:text-cyan-400 transition-colors truncate"
          >
            {b.player.name}
          </Link>
          <span className="text-[11px] text-zinc-500 shrink-0">{pick.teamAbbr}</span>
          {!pick.lineupConfirmed && (
            <span className="text-[10px] text-amber-300/80 shrink-0" title="Projected lineup">
              proj
            </span>
          )}
        </div>
        <div className="text-[11px] text-zinc-500 truncate">
          vs {pick.opponentAbbr} {hand(pick)} {pick.opposingPitcherName} · {why}
        </div>
      </div>
      <div className={cn('font-mono tabular-nums text-sm shrink-0 w-16 text-right', valueClass)}>
        {value}
      </div>
      <OddsSlot />
    </div>
  )
}

// ── why strings (model-derived, never invented odds) ──────────────────────────

function hitWhy(pick: FlatBatterPick): string {
  const b = pick.batter
  const parts: string[] = [`${pct(b.probabilities.hit1plus)} hit prob vs ${hand(pick)}`]
  if (b.matchupXwoba != null) parts.push(`${b.matchupXwoba.toFixed(3)} xwOBA matchup`)
  return parts.join(' — ')
}

function hrWhy(pick: FlatBatterPick): string {
  const b = pick.batter
  const parts: string[] = [`${pct(b.probabilities.hr)} HR prob`]
  const park = b.adjustments?.park
  if (park != null && Math.abs(park - 1) > 0.02) parts.push(`park ×${park.toFixed(2)}`)
  if (b.matchupXwoba != null) parts.push(`${b.matchupXwoba.toFixed(3)} xwOBA`)
  return parts.join(' — ')
}

function tbWhy(pick: FlatBatterPick): string {
  const b = pick.batter
  return `${b.expectedHits.toFixed(2)} xH · ${b.expectedPa.toFixed(1)} PA vs ${hand(pick)}`
}

// ── boards ────────────────────────────────────────────────────────────────────

function heat(level: 'hi' | 'mid' | 'lo') {
  return level === 'hi'
    ? 'text-emerald-400 font-semibold'
    : level === 'mid'
      ? 'text-emerald-300'
      : 'text-zinc-200'
}

function BetBoards({ picks }: { picks: FlatBatterPick[] }) {
  const byHit = [...picks]
    .sort((a, b) => b.batter.probabilities.hit1plus - a.batter.probabilities.hit1plus)
    .slice(0, N)

  const byHr = [...picks]
    .sort((a, b) => b.batter.probabilities.hr - a.batter.probabilities.hr)
    .slice(0, N)

  const byTb = [...picks]
    .sort((a, b) => b.batter.expectedTotalBases - a.batter.expectedTotalBases)
    .slice(0, N)

  return (
    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
      <BoardCard
        title="Most Likely To Get a Hit"
        blurb="Highest model P(H≥1) across today's slate. Model edge, not a posted line."
      >
        {byHit.length === 0 ? (
          <EmptyBoard />
        ) : (
          byHit.map((p, i) => (
            <BetRow
              key={`${p.gameId}-${p.batter.player.id}`}
              rank={i + 1}
              pick={p}
              value={pct(p.batter.probabilities.hit1plus)}
              valueClass={heat(
                p.batter.probabilities.hit1plus > 0.75
                  ? 'hi'
                  : p.batter.probabilities.hit1plus > 0.6
                    ? 'mid'
                    : 'lo',
              )}
              why={hitWhy(p)}
            />
          ))
        )}
      </BoardCard>

      <BoardCard
        title="Power Picks (HR)"
        blurb="Highest model P(HR) — matchup, park, and weather driven."
      >
        {byHr.length === 0 ? (
          <EmptyBoard />
        ) : (
          byHr.map((p, i) => (
            <BetRow
              key={`${p.gameId}-${p.batter.player.id}`}
              rank={i + 1}
              pick={p}
              value={pct(p.batter.probabilities.hr)}
              valueClass={heat(
                p.batter.probabilities.hr > 0.12
                  ? 'hi'
                  : p.batter.probabilities.hr > 0.08
                    ? 'mid'
                    : 'lo',
              )}
              why={hrWhy(p)}
            />
          ))
        )}
      </BoardCard>

      <BoardCard
        title="Best Total Bases"
        blurb="Highest projected total bases (xTB)."
      >
        {byTb.length === 0 ? (
          <EmptyBoard />
        ) : (
          byTb.map((p, i) => (
            <BetRow
              key={`${p.gameId}-${p.batter.player.id}`}
              rank={i + 1}
              pick={p}
              value={p.batter.expectedTotalBases.toFixed(2)}
              valueClass="text-cyan-300"
              why={tbWhy(p)}
            />
          ))
        )}
      </BoardCard>
    </div>
  )
}

// ── skeletons ─────────────────────────────────────────────────────────────────

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={cn('animate-pulse bg-white/5 rounded', className)} />
}

function BoardSkeleton() {
  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl p-4 space-y-3">
      <Skeleton className="h-4 w-44" />
      <Skeleton className="h-3 w-56" />
      {Array.from({ length: 6 }).map((_, i) => (
        <Skeleton key={i} className="h-7 w-full" />
      ))}
    </div>
  )
}

// ── page body ─────────────────────────────────────────────────────────────────

export function BestBetsBoard() {
  const { games, picks, isPending, isError, projectionsLoading } = usePicks()

  const projectedGames = games.filter((g) => g.projection)
  const hasContent = picks.length > 0 || projectedGames.length > 0
  const loading = isPending || (projectionsLoading && picks.length === 0)

  return (
    <main className="max-w-6xl mx-auto w-full px-4 py-8">
      <div className="mb-8">
        <div className={microLabel}>Top Bets</div>
        <h1 className="text-3xl font-bold tracking-tight text-zinc-100 mt-1">Best Bets</h1>
        <p className="text-zinc-500 text-sm mt-1">
          The model&apos;s strongest leans across today&apos;s MLB slate — ranked by projection,
          not by any posted price.
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
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          {Array.from({ length: 3 }).map((_, i) => (
            <BoardSkeleton key={i} />
          ))}
        </div>
      ) : !hasContent || picks.length === 0 ? (
        <p className="text-zinc-500 text-sm bg-[#0e1015] border border-white/10 rounded-xl p-6">
          No projections yet — probable pitchers or lineups aren&apos;t confirmed for today&apos;s
          games. Check back closer to first pitch.
        </p>
      ) : (
        <BetBoards picks={picks} />
      )}

      <p className="mt-6 text-[11px] text-zinc-600">
        Sportsbook odds and EV% are coming soon — for now these are pure model edges.
        Tennis best bets are coming soon.
      </p>
    </main>
  )
}
