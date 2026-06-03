'use client'

import Link from 'next/link'
import type { FlatBatterPick, TodayGame } from '@/lib/types'
import { cn } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

function pct(v: number | null | undefined) {
  if (v == null) return '—'
  return (v * 100).toFixed(0) + '%'
}

// Positive heat scale for hit/HR/TB style metrics (warmer = stronger pick).
function goodHeat(level: 'hi' | 'mid' | 'lo') {
  return level === 'hi'
    ? 'text-emerald-400 font-semibold'
    : level === 'mid'
      ? 'text-emerald-300'
      : 'text-zinc-300'
}

// ── shared card shell ────────────────────────────────────────────────────────

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

// The reserved slot for a future sportsbook number (see plan: odds come later).
function OddsSlot() {
  return (
    <div className="text-right shrink-0 w-12">
      {/* TODO: sportsbook odds — wire real money line / over-under here */}
      <div className={microLabel}>Odds</div>
      <div className="text-xs text-zinc-600 font-mono">—</div>
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

// ── batter rows ──────────────────────────────────────────────────────────────

function BatterRow({
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
  const hand = pick.opposingPitcherThrows === 'L' ? 'LHP' : 'RHP'
  return (
    <div className="flex items-center gap-3 px-4 py-2 hover:bg-white/[0.03] transition-colors">
      <Rank n={rank} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          <Link
            href={`/players/${b.player.id}`}
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
          vs {pick.opponentAbbr} {hand} {pick.opposingPitcherName} · {why}
        </div>
      </div>
      <div className={cn('font-mono tabular-nums text-sm shrink-0 w-14 text-right', valueClass)}>
        {value}
      </div>
      <OddsSlot />
    </div>
  )
}

function matchupWhy(pick: FlatBatterPick): string {
  const b = pick.batter
  const parts: string[] = []
  if (b.matchupXwoba != null) parts.push(`xwOBA ${b.matchupXwoba.toFixed(3)}`)
  parts.push(`${b.expectedPa.toFixed(1)} PA`)
  return parts.join(' · ')
}

function hrWhy(pick: FlatBatterPick): string {
  const b = pick.batter
  const parts: string[] = []
  const park = b.adjustments?.park
  if (park != null && Math.abs(park - 1) > 0.02) parts.push(`Park ×${park.toFixed(2)}`)
  if (b.matchupXwoba != null) parts.push(`xwOBA ${b.matchupXwoba.toFixed(3)}`)
  if (parts.length === 0) parts.push(`${b.expectedPa.toFixed(1)} PA`)
  return parts.join(' · ')
}

// ── board builders ───────────────────────────────────────────────────────────

const N = 6

export function BatterBoards({ picks }: { picks: FlatBatterPick[] }) {
  const byHit = [...picks]
    .sort((a, b) => b.batter.probabilities.hit1plus - a.batter.probabilities.hit1plus)
    .slice(0, N)

  const byHr = [...picks]
    .sort((a, b) => b.batter.probabilities.hr - a.batter.probabilities.hr)
    .slice(0, N)

  const byTb = [...picks]
    .sort((a, b) => b.batter.expectedTotalBases - a.batter.expectedTotalBases)
    .slice(0, N)

  const byContact = [...picks]
    .filter((p) => p.batter.expectedPa >= 3.5)
    .sort((a, b) => a.batter.probabilities.k1plus - b.batter.probabilities.k1plus)
    .slice(0, N)

  return (
    <>
      <BoardCard
        title="Most Likely To Get a Hit"
        blurb="Highest P(H≥1) across the slate — model projection, not odds."
      >
        {byHit.map((p, i) => (
          <BatterRow
            key={`${p.gameId}-${p.batter.player.id}`}
            rank={i + 1}
            pick={p}
            value={pct(p.batter.probabilities.hit1plus)}
            valueClass={goodHeat(
              p.batter.probabilities.hit1plus > 0.75 ? 'hi' : p.batter.probabilities.hit1plus > 0.6 ? 'mid' : 'lo',
            )}
            why={matchupWhy(p)}
          />
        ))}
      </BoardCard>

      <BoardCard
        title="Power Picks (HR)"
        blurb="Highest P(HR) — driven by matchup, park, and weather."
      >
        {byHr.map((p, i) => (
          <BatterRow
            key={`${p.gameId}-${p.batter.player.id}`}
            rank={i + 1}
            pick={p}
            value={pct(p.batter.probabilities.hr)}
            valueClass={goodHeat(
              p.batter.probabilities.hr > 0.12 ? 'hi' : p.batter.probabilities.hr > 0.08 ? 'mid' : 'lo',
            )}
            why={hrWhy(p)}
          />
        ))}
      </BoardCard>

      <BoardCard
        title="Best Total Bases"
        blurb="Highest expected total bases (xTB)."
      >
        {byTb.map((p, i) => (
          <BatterRow
            key={`${p.gameId}-${p.batter.player.id}`}
            rank={i + 1}
            pick={p}
            value={p.batter.expectedTotalBases.toFixed(2)}
            valueClass="text-zinc-100"
            why={`${p.batter.expectedHits.toFixed(2)} xH · ${p.batter.expectedPa.toFixed(1)} PA`}
          />
        ))}
      </BoardCard>

      <BoardCard
        title="Safest Contact (Low K)"
        blurb="Lowest P(K) among everyday bats (≥3.5 PA)."
      >
        {byContact.map((p, i) => (
          <BatterRow
            key={`${p.gameId}-${p.batter.player.id}`}
            rank={i + 1}
            pick={p}
            value={pct(p.batter.probabilities.k1plus)}
            valueClass="text-emerald-300"
            why={`${p.batter.expectedPa.toFixed(1)} PA`}
          />
        ))}
      </BoardCard>
    </>
  )
}

// ── game-level boards (totals + model favorites) ─────────────────────────────

function GameRow({
  rank,
  game,
  value,
  valueClass,
  why,
}: {
  rank: number
  game: TodayGame
  value: string
  valueClass?: string
  why: string
}) {
  return (
    <Link
      href={`/games/${game.gameId}`}
      className="flex items-center gap-3 px-4 py-2 hover:bg-white/[0.03] transition-colors"
    >
      <Rank n={rank} />
      <div className="min-w-0 flex-1">
        <div className="font-medium text-zinc-100 truncate">
          {game.away.abbr} <span className="text-zinc-600">@</span> {game.home.abbr}
        </div>
        <div className="text-[11px] text-zinc-500 truncate">{why}</div>
      </div>
      <div className={cn('font-mono tabular-nums text-sm shrink-0 w-16 text-right', valueClass)}>
        {value}
      </div>
      <OddsSlot />
    </Link>
  )
}

export function GameBoards({ games }: { games: TodayGame[] }) {
  const projected = games.filter((g) => g.projection)

  const byTotal = [...projected]
    .sort((a, b) => (b.projection!.expectedTotal ?? 0) - (a.projection!.expectedTotal ?? 0))
    .slice(0, N)

  const byMargin = [...projected]
    .map((g) => {
      const h = g.projection!.expectedHomeRuns ?? 0
      const a = g.projection!.expectedAwayRuns ?? 0
      const margin = h - a
      return { g, margin, fav: margin >= 0 ? g.home.abbr : g.away.abbr, mag: Math.abs(margin) }
    })
    .sort((x, y) => y.mag - x.mag)
    .slice(0, N)

  return (
    <>
      <BoardCard
        title="Top Scoring Games"
        blurb="Highest projected combined run total."
      >
        {byTotal.map((g, i) => (
          <GameRow
            key={g.gameId}
            rank={i + 1}
            game={g}
            value={`${g.projection!.expectedTotal!.toFixed(1)} R`}
            valueClass="text-cyan-300"
            why={`${g.home.abbr} ${g.projection!.expectedHomeRuns!.toFixed(1)} · ${g.away.abbr} ${g.projection!.expectedAwayRuns!.toFixed(1)}`}
          />
        ))}
      </BoardCard>

      <BoardCard
        title="Model Favorites"
        blurb="Biggest projected run margin (the model's money-line lean)."
      >
        {byMargin.map(({ g, fav, mag }, i) => (
          <GameRow
            key={g.gameId}
            rank={i + 1}
            game={g}
            value={`+${mag.toFixed(1)}`}
            valueClass="text-emerald-300"
            why={`${fav} favored by ${mag.toFixed(1)} R`}
          />
        ))}
      </BoardCard>
    </>
  )
}
