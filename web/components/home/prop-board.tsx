'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Target } from 'lucide-react'
import { propBoardQueryOptions } from '@/lib/api'
import type { PitcherPropPick, PropBoardPick } from '@/lib/types'
import { cn } from '@/lib/utils'
import { bookLabel, formatAmerican } from '@/lib/odds'
import { WhyDisclosure } from './why-disclosure'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

const PITCH_NAMES: Record<string, string> = {
  FF: '4-seam', SI: 'sinker', FC: 'cutter', SL: 'slider', CU: 'curve',
  CH: 'changeup', FS: 'splitter', KC: 'knuckle-curve', ST: 'sweeper', SV: 'slurve',
}

function pitchName(code: string) {
  return PITCH_NAMES[code] ?? code
}

// Park/weather multipliers within this band of 1.0 are noise, not narrative.
const ADJ_NOTEWORTHY = 0.03

const MARKET_META: Record<string, { chip: string; verb: string }> = {
  hit: { chip: 'Hit', verb: 'to record a hit' },
  hr: { chip: 'Home Run', verb: 'to homer' },
  k: { chip: 'Strikeout', verb: 'to strike out at least once' },
  bb: { chip: 'Walk', verb: 'to draw a walk' },
}

const PITCHER_MARKET_META: Record<string, { chip: string; unit: string; noun: string }> = {
  pitcher_k: { chip: 'Pitcher Ks', unit: 'K', noun: 'strikeouts' },
  pitcher_outs: { chip: 'Outs', unit: 'outs', noun: 'outs recorded' },
  pitcher_hits_allowed: { chip: 'Hits allowed', unit: 'H', noun: 'hits allowed' },
  pitcher_earned_runs: { chip: 'Earned runs', unit: 'ER', noun: 'earned runs' },
}

function pct(v: number) {
  return (v * 100).toFixed(1) + '%'
}

function signedPctFromAdj(adj: number) {
  const delta = (adj - 1) * 100
  return (delta > 0 ? '+' : '') + delta.toFixed(0) + '%'
}

function xwoba(v: number) {
  return v.toFixed(3).replace(/^0/, '')
}

function ordinal(n: number) {
  const s = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return n + (s[(v - 20) % 10] ?? s[v] ?? s[0])
}

// The reasoning bullets, built from the projection's own factors — no odds required.
function buildReasons(p: PropBoardPick): string[] {
  const reasons: string[] = []

  if (p.expectedPa != null && p.lineupPosition != null) {
    reasons.push(
      `Batting ${ordinal(p.lineupPosition)} (${
        p.lineupConfirmed ? 'confirmed lineup' : 'projected lineup'
      }) for ${p.expectedPa.toFixed(1)} expected plate appearances — every extra trip to the plate compounds the chance.`,
    )
  }

  if (p.opposingPitcher) {
    // matchup xwOBA is a hit/power signal — irrelevant to drawing a walk, so the
    // walk card just names the pitcher.
    if (p.market !== 'bb' && p.matchupXwoba != null) {
      const basis =
        p.matchupQuality === 'matchup'
          ? 'his swing profile against this exact pitch mix'
          : 'overall profiles (limited head-to-head pitch-mix sample)'
      reasons.push(
        `Faces ${p.opposingPitcher}: matchup xwOBA ${xwoba(p.matchupXwoba)}, built from ${basis}.`,
      )
    } else {
      reasons.push(`Faces ${p.opposingPitcher}.`)
    }
  }

  // Park / weather move balls in play and carry — not plate discipline. Skip for walks.
  const env: string[] = []
  if (p.market !== 'bb' && p.adjPark != null && Math.abs(p.adjPark - 1) >= ADJ_NOTEWORTHY) {
    env.push(
      `${p.stadium ?? 'the park'} plays ${signedPctFromAdj(p.adjPark)} for this stat`,
    )
  }
  if (p.market !== 'bb' && p.adjWeather != null && Math.abs(p.adjWeather - 1) >= ADJ_NOTEWORTHY) {
    env.push(`today's weather adds ${signedPctFromAdj(p.adjWeather)}`)
  }
  if (env.length > 0) {
    reasons.push(env.join('; ') + '.')
  }

  // Opposing-team defense (hit card only): the leak-free xBA hit-suppression factor.
  // < 1 means the defense takes hits away (headwind for the over); > 1 means it leaks them.
  if (
    p.market === 'hit' &&
    p.adjDefense != null &&
    Math.abs(p.adjDefense - 1) >= ADJ_NOTEWORTHY
  ) {
    const delta = Math.round(Math.abs(p.adjDefense - 1) * 100)
    reasons.push(
      p.adjDefense < 1
        ? `Opposing defense is suppressing hits — ${delta}% below average on balls in play (a headwind for this over).`
        : `Opposing defense is leaking hits — ${delta}% above average on balls in play (a tailwind here).`,
    )
  }

  // Park fit (HR card only): the batter's pull tendency against the fence his
  // handedness targets. Raw facts — the model's personalization stays server-side.
  if (
    p.market === 'hr' &&
    p.pullPct != null &&
    p.pullFenceFt != null &&
    (p.bats === 'R' || p.bats === 'L')
  ) {
    const field = p.bats === 'R' ? 'left-field' : 'right-field'
    const wall = p.pullWallFt != null ? ` (${Math.round(p.pullWallFt)}-ft wall)` : ''
    const ev =
      p.avgLaunchSpeed != null
        ? `; ${p.avgLaunchSpeed.toFixed(1)} mph average exit velocity`
        : ''
    reasons.push(
      `Park fit: pulls ${Math.round(p.pullPct * 100)}% of his balls in play toward the ${Math.round(
        p.pullFenceFt,
      )}-ft ${field} fence${wall}${ev}.`,
    )
  }

  // Season rate leads — it's the meaningful base rate. The last-10 count is
  // appended as context only (short windows are hot-hand noise, not signal).
  if (p.rateSeason != null && p.nSeason != null) {
    const l10 =
      p.rateL10 != null ? ` (${Math.round(p.rateL10 * 10)} of his last 10)` : ''
    reasons.push(
      `Has cleared in ${pct(p.rateSeason)} of his ${p.nSeason} games this season${l10}.`,
    )
  } else if (p.rateL10 != null) {
    reasons.push(`Has cleared in ${Math.round(p.rateL10 * 10)} of his last 10 games.`)
  }

  if (p.priceAmerican != null && p.evPct != null) {
    reasons.push(
      `Best cached price ${formatAmerican(p.priceAmerican)} (${bookLabel(p.bestBook)}) — ${
        p.evPct > 0 ? '+' : ''
      }${(p.evPct * 100).toFixed(1)}% EV at the model's number. Cached lines can be stale; treat as context.`,
    )
  }

  return reasons
}

// A single compact factor, shown in the inline flex row both card types share.
function Factor({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <div className={microLabel}>{label}</div>
      <div className="text-[13px] font-mono tabular-nums text-zinc-300">{value}</div>
    </div>
  )
}

// ── runners-up: one compact muted line, shared by batter + pitcher cards ─────────

function RunnersUpLine({
  accent,
  items,
}: {
  accent: 'cyan' | 'amber'
  items: { id: number; name: string; team: string; href: string; value: string }[]
}) {
  if (items.length === 0) return null
  const hover = accent === 'amber' ? 'hover:text-amber-300' : 'hover:text-cyan-400'
  return (
    <div className="pt-2 border-t border-white/5 text-xs text-zinc-500">
      <span className={microLabel}>Also&nbsp;</span>
      {items.map((it, i) => (
        <span key={it.id}>
          {i > 0 && <span className="text-zinc-700"> · </span>}
          <Link href={it.href} className={`text-zinc-400 transition-colors ${hover}`}>
            {it.name}
          </Link>{' '}
          <span className="text-zinc-600">{it.team}</span>{' '}
          <span className="font-mono tabular-nums text-zinc-400">{it.value}</span>
        </span>
      ))}
    </div>
  )
}

function PropCard({ pick }: { pick: PropBoardPick }) {
  const meta = MARKET_META[pick.market] ?? { chip: pick.market, verb: pick.market }
  return (
    <div className="rounded-xl border border-white/10 bg-[#0e1015] px-5 py-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border text-cyan-300 border-cyan-400/40 bg-cyan-500/10">
          {meta.chip}
        </span>
        <Link
          href={`/mlb/games/${pick.gameId}`}
          className="ml-auto font-mono text-xs text-zinc-500 hover:text-cyan-400 transition-colors"
        >
          {pick.matchup}
        </Link>
      </div>

      <div className="flex items-baseline justify-between gap-3">
        <Link
          href={`/mlb/players/${pick.playerId}`}
          className="text-base font-bold tracking-tight text-zinc-100 hover:text-cyan-300 transition-colors"
        >
          {pick.player}{' '}
          <span className="text-sm font-normal text-zinc-500">{meta.verb}</span>
        </Link>
        <span className="shrink-0 font-mono tabular-nums text-lg text-cyan-300">
          {pct(pick.prob)}
        </span>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <Factor label="xPA" value={pick.expectedPa != null ? pick.expectedPa.toFixed(1) : '—'} />
        {pick.matchupXwoba != null && <Factor label="Matchup" value={xwoba(pick.matchupXwoba)} />}
        <Factor
          label="Last 10"
          value={pick.rateL10 == null ? '—' : `${Math.round(pick.rateL10 * 10)}/10`}
        />
        <Factor
          label="Best price"
          value={
            pick.priceAmerican == null
              ? 'no line'
              : `${formatAmerican(pick.priceAmerican)} ${bookLabel(pick.bestBook)}`
          }
        />
      </div>

      <WhyDisclosure reasons={buildReasons(pick)} />

      <RunnersUpLine
        accent="cyan"
        items={pick.runnersUp.map((ru) => ({
          id: ru.playerId,
          name: ru.player,
          team: ru.team,
          href: `/mlb/players/${ru.playerId}`,
          value: pct(ru.prob),
        }))}
      />
    </div>
  )
}

// One-line summary of the pitcher's mix: his most-thrown pitch (usage/whiff/velo) and,
// when different, his best swing-and-miss offering — the real K driver.
function arsenalNote(pick: PitcherPropPick): string | null {
  const arsenal = pick.arsenal ?? []
  if (arsenal.length === 0) return null
  const top = arsenal[0]
  const bits: string[] = []
  if (top.usageRate != null) bits.push(`${Math.round(top.usageRate * 100)}% usage`)
  if (top.whiffRate != null) bits.push(`${Math.round(top.whiffRate * 100)}% whiff`)
  if (top.avgVelocity != null) bits.push(`${top.avgVelocity.toFixed(0)} mph`)
  let note = `Leans on his ${pitchName(top.pitchType)}${bits.length ? ` (${bits.join(', ')})` : ''}.`
  const swing = [...arsenal]
    .filter((p) => p.whiffRate != null)
    .sort((a, b) => (b.whiffRate as number) - (a.whiffRate as number))[0]
  if (swing && swing.pitchType !== top.pitchType && swing.whiffRate != null) {
    note += ` Best whiff pitch: the ${pitchName(swing.pitchType)} at ${Math.round(
      swing.whiffRate * 100,
    )}%.`
  }
  return note
}

// The pitcher card's reasoning bullets — the actual DRIVERS of the line (the header
// number + the over-distribution row already show the projection itself). Built from the
// pitcher's own profile (K/BB/xwOBA-against/HR), his arsenal, and the lineup he faces.
function buildPitcherReasons(pick: PitcherPropPick): string[] {
  const reasons: string[] = []
  const kMarket = pick.market === 'pitcher_k' || pick.market === 'pitcher_outs'

  // The pitcher's own season profile.
  const profile: string[] = []
  if (pick.pitcherKRate != null) profile.push(`${pct(pick.pitcherKRate)} K`)
  if (pick.pitcherBbRate != null) profile.push(`${pct(pick.pitcherBbRate)} BB`)
  if (pick.pitcherXwobaAgainst != null) {
    profile.push(`${xwoba(pick.pitcherXwobaAgainst)} xwOBA against`)
  }
  if (profile.length > 0) {
    const hr =
      pick.pitcherHrPerPa != null
        ? `, allows a homer on ${(pick.pitcherHrPerPa * 100).toFixed(1)}% of PAs`
        : ''
    reasons.push(`Season profile: ${profile.join(' · ')}${hr}.`)
  }

  // His mix — arsenal-led, the strongest signal for a strikeout line.
  const arsenal = arsenalNote(pick)
  if (arsenal) reasons.push(arsenal)

  // The lineup he faces.
  if (kMarket) {
    if (pick.opponentKRate != null) {
      const xw =
        pick.opponentXwoba != null ? ` (hitting ${xwoba(pick.opponentXwoba)} xwOBA)` : ''
      reasons.push(`The ${pick.opponent} lineup strikes out ${pct(pick.opponentKRate)}${xw}.`)
    }
  } else if (pick.opponentXwoba != null) {
    const k =
      pick.opponentKRate != null
        ? ` and strikes out ${pct(pick.opponentKRate)} of the time`
        : ''
    reasons.push(`The ${pick.opponent} lineup is hitting ${xwoba(pick.opponentXwoba)} xwOBA${k}.`)
  } else if (pick.opponentKRate != null) {
    reasons.push(`The ${pick.opponent} lineup strikes out ${pct(pick.opponentKRate)} of the time.`)
  }

  // Early-season fallback when no skill rows exist yet: name the projection so the
  // card never renders an empty reasoning list.
  if (reasons.length === 0) {
    const meta = PITCHER_MARKET_META[pick.market]
    reasons.push(
      `Projects for ${pick.expectedValue.toFixed(1)} ${
        meta?.noun ?? pick.market
      } against ${pick.opponent}.`,
    )
  }

  // The full over-ladder, for the curious — the headline is the single best pick.
  if (pick.distribution.length > 0) {
    const meta = PITCHER_MARKET_META[pick.market]
    const ladder = pick.distribution
      .map((t) => `over ${t.line} → ${pct(t.prob)}`)
      .join(', ')
    reasons.push(`Full distribution (${meta?.noun ?? pick.market}): ${ladder}.`)
  }

  if (pick.priceAmerican != null && pick.bookLine != null) {
    const side = pick.bestSide ?? 'over'
    const ev =
      pick.evPct != null
        ? ` — ${pick.evPct > 0 ? '+' : ''}${(pick.evPct * 100).toFixed(1)}% EV at the model's number`
        : ''
    reasons.push(
      `Best ${side} price on the ${pick.bookLine} line: ${formatAmerican(pick.priceAmerican)} (${bookLabel(
        pick.bestBook,
      )})${ev}. Cached lines can be stale; treat as context.`,
    )
  }
  return reasons
}

// The single recommended pick: the side the model leans (over/under) at the most
// relevant line, with model probability and — when odds exist — the best price + EV
// for that side. Replaces the old over-only ladder (which buried the actual pick).
function BestPick({ pick, unit }: { pick: PitcherPropPick; unit: string }) {
  if (pick.bestSide == null || pick.bestLine == null || pick.bestProb == null) return null
  const side = pick.bestSide === 'over' ? 'Over' : 'Under'
  const hasEv = pick.evPct != null && pick.priceAmerican != null
  return (
    <div className="rounded-lg border border-amber-400/20 bg-amber-500/[0.06] px-3 py-2 flex flex-wrap items-baseline gap-x-3 gap-y-1">
      <span className={microLabel}>Best pick</span>
      <span className="text-sm font-semibold text-amber-100">
        {side} {pick.bestLine} {unit}
      </span>
      <span className="font-mono tabular-nums text-amber-300">{pct(pick.bestProb)}</span>
      {hasEv && (
        <span className="ml-auto text-xs text-zinc-500">
          {formatAmerican(pick.priceAmerican as number)} {bookLabel(pick.bestBook)} ·{' '}
          <span className={(pick.evPct as number) > 0 ? 'text-emerald-400' : 'text-zinc-500'}>
            {(pick.evPct as number) > 0 ? '+' : ''}
            {((pick.evPct as number) * 100).toFixed(1)}% EV
          </span>
        </span>
      )}
    </div>
  )
}

// Pitcher cards are AMBER (batter cards are cyan) so "whose prop is this" is never
// ambiguous — these are the starter's line, ranked by expected volume; the headline
// number is the projection, the Best pick row is the model's lean (over or under).
function PitcherCard({ pick }: { pick: PitcherPropPick }) {
  const meta =
    PITCHER_MARKET_META[pick.market] ?? { chip: pick.market, unit: '', noun: pick.market }

  const reasons = buildPitcherReasons(pick)

  return (
    <div className="rounded-xl border border-amber-400/20 bg-[#0e1015] px-5 py-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border text-amber-300 border-amber-400/40 bg-amber-500/10">
          {meta.chip}
        </span>
        <span className="text-[10px] uppercase tracking-[0.12em] text-zinc-600">Pitcher</span>
        <Link
          href={`/mlb/games/${pick.gameId}`}
          className="ml-auto font-mono text-xs text-zinc-500 hover:text-amber-300 transition-colors"
        >
          {pick.matchup}
        </Link>
      </div>

      <div className="flex items-baseline justify-between gap-3">
        <Link
          href={`/mlb/players/${pick.pitcherId}`}
          className="text-base font-bold tracking-tight text-zinc-100 hover:text-amber-200 transition-colors"
        >
          {pick.pitcher}{' '}
          <span className="text-sm font-normal text-zinc-500">vs {pick.opponent}</span>
        </Link>
        <span className="shrink-0 font-mono tabular-nums text-lg text-amber-300">
          {pick.expectedValue.toFixed(1)}{' '}
          <span className="text-zinc-500 text-xs">{meta.unit}</span>
        </span>
      </div>

      <BestPick pick={pick} unit={meta.unit} />

      <WhyDisclosure reasons={reasons} />

      <RunnersUpLine
        accent="amber"
        items={pick.runnersUp.map((ru) => ({
          id: ru.pitcherId,
          name: ru.pitcher,
          team: ru.team,
          href: `/mlb/players/${ru.pitcherId}`,
          value: `${ru.expectedValue.toFixed(1)} ${meta.unit}`,
        }))}
      />
    </div>
  )
}

function Skeleton({ className = '' }: { className?: string }) {
  return <div className={cn('animate-pulse bg-white/5 rounded', className)} />
}

/**
 * Model-first prop board: one card per prop market with the model's most likely
 * batter and the reasoning. Unlike Model's Picks this never needs live odds — it
 * ranks by likelihood, not value, so it keeps working when the odds feed is off.
 */
export function PropBoard() {
  const { data, isPending, isError } = useQuery(propBoardQueryOptions())

  return (
    <section className="mb-10">
      <div className="mb-3">
        <h2 className="text-sm font-semibold tracking-tight text-zinc-100 flex items-center gap-1.5">
          <Target className="h-4 w-4 text-cyan-300" aria-hidden="true" />
          Prop Board
        </h2>
        <p className="text-xs text-zinc-500 mt-0.5">
          The model&apos;s most likely batter in each prop market — likelihood, not value.
          Straight from our projections, with the reasoning; no sportsbook feed required.
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
          Couldn&apos;t load the prop board right now.
        </p>
      ) : data.picks.length === 0 ? (
        <p className="text-sm text-zinc-500 bg-[#0e1015] border border-white/10 rounded-xl px-5 py-4">
          No batter projections for today&apos;s slate yet — the board fills in once
          projections run.
        </p>
      ) : (
        <div
          className={cn(
            'grid gap-4',
            data.picks.length === 1 && 'lg:max-w-xl',
            // 2 or 4 cards → 2 columns (4 fills a clean 2×2, no stray empty cells);
            // 3 (or the rare 5+) → 3 columns so the last row still fills.
            (data.picks.length === 2 || data.picks.length === 4) && 'lg:grid-cols-2',
            (data.picks.length === 3 || data.picks.length >= 5) && 'lg:grid-cols-3',
          )}
        >
          {data.picks.map((pick) => (
            <PropCard key={pick.market} pick={pick} />
          ))}
        </div>
      )}

      {!isPending && !isError && data.pitcherPicks.length > 0 && (
        <div className="mt-6">
          <p className={cn(microLabel, 'mb-2')}>
            Pitcher props — top starter by projected volume, with the model&apos;s best pick (over/under)
          </p>
          <div
            className={cn(
              'grid gap-4',
              data.pitcherPicks.length === 1 && 'lg:max-w-xl',
              data.pitcherPicks.length >= 2 && 'lg:grid-cols-2',
            )}
          >
            {data.pitcherPicks.map((pick) => (
              <PitcherCard key={pick.market} pick={pick} />
            ))}
          </div>
        </div>
      )}
    </section>
  )
}
