'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Target } from 'lucide-react'
import {
  livePlayerResultsQueryOptions,
  lottoQueryOptions,
  playerResultsQueryOptions,
  propBoardQueryOptions,
  todayGamesQueryOptions,
} from '@/lib/api'
import type {
  BatterResult,
  BoomPick,
  PitcherPropPick,
  PitcherResult,
  PropBoardPick,
  TodayGame,
} from '@/lib/types'
import { cn } from '@/lib/utils'
import { bookLabel, formatAmerican } from '@/lib/odds'
import { liveCountOutcome, overUnderOutcome, propOutcome, type PickOutcome } from '@/lib/picks'
import { OutcomeBadge } from './outcome-badge'
import { LivePropTracker, gameIsLive } from './live-tracker'
import { WhyDisclosure } from './why-disclosure'
import { microLabel, Skeleton } from '@/components/ui/primitives'
import { pct, signed } from '@/lib/format'

const PITCH_NAMES: Record<string, string> = {
  FF: '4-seam', SI: 'sinker', FC: 'cutter', SL: 'slider', CU: 'curve',
  CH: 'changeup', FS: 'splitter', KC: 'knuckle-curve', ST: 'sweeper', SV: 'slurve',
}

function pitchName(code: string) {
  return PITCH_NAMES[code] ?? code
}

// Park/weather multipliers within this band of 1.0 are noise, not narrative.
const ADJ_NOTEWORTHY = 0.03
// Projected HR carry (ft) at/above which we flag a HR pick as "long-ball upside" — a real shot
// at the day's longest-HR bonus. Absolute (not slate-relative) on purpose: the bonus is about
// actual distance in tonight's park/weather, so a masher in a dead park can drop below it.
const LONG_BALL_UPSIDE_FT = 430

// League-average pitcher rates (per PA) for framing the walk card's control narrative.
// Mirror the model's constants in ingester/ingester/projection/constants.py.
const LEAGUE_PITCHER_BB_RATE = 0.085
const LEAGUE_PITCHER_K_RATE = 0.225
// How far the pitcher's walk rate must sit from league (±) before we call it wildness or
// strong control rather than league-average — below this it's noise, not narrative.
const BB_CONTROL_BAND = 0.15
// A starter whose K rate is this far below league is a pitch-to-contact arm — worth noting
// on the walk card since contact pitchers tend not to give away free passes.
const CONTACT_ARM_BAND = 0.15

// verb bakes in the line: hrr/tb clear a 1.5 line (2+), hr/bb a 0.5 line (1+).
const MARKET_META: Record<string, { chip: string; verb: string }> = {
  hrr: { chip: 'H+R+RBI', verb: 'to total 2+ hits + runs + RBI' },
  hr: { chip: 'Home Run', verb: 'to homer' },
  tb: { chip: 'Total Bases', verb: 'to record 2+ total bases' },
  bb: { chip: 'Walk', verb: 'to draw a walk' },
}

// Stat unit shown in the live prop tracker, per batter market.
const BATTER_UNIT: Record<string, string> = { hrr: 'H+R+RBI', hr: 'HR', tb: 'TB', bb: 'BB' }

const PITCHER_MARKET_META: Record<string, { chip: string; unit: string; noun: string }> = {
  pitcher_k: { chip: 'Pitcher Ks', unit: 'K', noun: 'strikeouts' },
  pitcher_outs: { chip: 'Outs', unit: 'outs', noun: 'outs recorded' },
  pitcher_hits_allowed: { chip: 'Hits allowed', unit: 'H', noun: 'hits allowed' },
  pitcher_earned_runs: { chip: 'Earned runs', unit: 'ER', noun: 'earned runs' },
}

// The actual result that grades each batter market once a game is final (or the live
// count while in progress). hrr is composite, so this is an accessor rather than a
// single field: undefined = no result row yet (pending), null = row exists but the
// stat isn't recorded (H+R+RBI needs boxscore runs/rbi), number = the count.
function batterActual(market: string, r: BatterResult | undefined): number | null | undefined {
  if (!r) return undefined
  switch (market) {
    case 'hr':
      return r.homeRuns
    case 'bb':
      return r.walks
    case 'tb':
      return r.totalBases
    case 'hrr':
      return r.hits == null || r.runs == null || r.rbi == null
        ? null
        : r.hits + r.runs + r.rbi
    default:
      return undefined
  }
}
const PITCHER_RESULT_FIELD: Record<string, keyof PitcherResult> = {
  pitcher_k: 'strikeouts', pitcher_outs: 'outs',
  pitcher_hits_allowed: 'hitsAllowed', pitcher_earned_runs: 'earnedRuns',
}

function signedPctFromAdj(adj: number) {
  return signed((adj - 1) * 100, 0) + '%'
}

function xwoba(v: number) {
  return v.toFixed(3).replace(/^0/, '')
}

function ordinal(n: number) {
  const s = ['th', 'st', 'nd', 'rd']
  const v = n % 100
  return n + (s[(v - 20) % 10] ?? s[v] ?? s[0])
}

// The walk card's reasoning: the opposing starter's control. Drawing a walk is mostly a
// function of how freely the pitcher gives them away, so we frame his walk rate against the
// league and characterize him — wild (tailwind for the over), strong control (headwind), or
// league-average. A notably low K rate flags a pitch-to-contact arm, which usually means
// even fewer free passes.
function walkControlReason(pitcher: string, bbRate: number, kRate: number | null): string {
  const delta = bbRate / LEAGUE_PITCHER_BB_RATE - 1
  const rel = `${signedPctFromAdj(bbRate / LEAGUE_PITCHER_BB_RATE)} vs. the league average`
  let read: string
  if (delta >= BB_CONTROL_BAND) {
    read = `${rel}, so he hands out free passes (a tailwind for this over)`
  } else if (delta <= -BB_CONTROL_BAND) {
    read = `${rel} — strong control, so he rarely walks anyone (a headwind here)`
  } else {
    read = `${rel}, roughly league-average control`
  }
  const contact =
    kRate != null && kRate <= LEAGUE_PITCHER_K_RATE * (1 - CONTACT_ARM_BAND)
      ? ` He's a pitch-to-contact arm (${pct(kRate)} K rate), which tends to mean even fewer walks.`
      : ''
  return `Faces ${pitcher}: he walks ${pct(bbRate)} of batters — ${read}.${contact}`
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
    // The walk card's driver is the pitcher's CONTROL, not matchup xwOBA (a hit/power
    // signal, irrelevant to drawing a walk). The hit/HR/K cards keep the xwOBA line.
    if (p.market === 'bb' && p.opposingPitcherBbRate != null) {
      reasons.push(walkControlReason(p.opposingPitcher, p.opposingPitcherBbRate, p.opposingPitcherKRate))
    } else if (p.market !== 'bb' && p.matchupXwoba != null) {
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

  // Opposing-team defense (hit-driven cards): the leak-free xBA hit-suppression factor.
  // < 1 means the defense takes hits away (headwind for the over); > 1 means it leaks them.
  // Total bases and H+R+RBI both ride on balls in play becoming hits, so it applies to both.
  if (
    (p.market === 'tb' || p.market === 'hrr') &&
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

  // Long-ball upside (HR card only): how far this HR would carry in tonight's park & weather —
  // the distance axis behind Fanatics' longest-HR bonus, separate from how LIKELY the HR is.
  // High variance, so it's framed as a tiebreaker, never a call on the day's longest.
  if (p.market === 'hr' && p.hrDistanceFt != null) {
    const tier = p.hrDistanceFt >= LONG_BALL_UPSIDE_FT ? ' — top-tier carry' : ''
    reasons.push(
      `Long-ball upside: this HR projects to carry ~${Math.round(
        p.hrDistanceFt,
      )} ft in tonight's park & weather${tier}. Fanatics pays extra if it's the day's longest HR — high variance, so weigh it as a tiebreaker.`,
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

function PropCard({
  pick,
  outcome,
  game,
  liveCount,
  liveOutcome,
  liveBatterLine,
}: {
  pick: PropBoardPick
  outcome?: PickOutcome
  game?: TodayGame
  liveCount?: number | null
  liveOutcome?: PickOutcome
  liveBatterLine?: { hits: number | null; atBats: number | null } | null
}) {
  const meta = MARKET_META[pick.market] ?? { chip: pick.market, verb: pick.market }
  return (
    <div className="rounded-xl border border-white/10 bg-[#0e1015] px-5 py-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border text-cyan-300 border-cyan-400/40 bg-cyan-500/10">
          {meta.chip}
        </span>
        {pick.market === 'hr' &&
          pick.hrDistanceFt != null &&
          pick.hrDistanceFt >= LONG_BALL_UPSIDE_FT && (
            <span
              title={`Projects to carry ~${Math.round(pick.hrDistanceFt)} ft tonight — a real shot at the day's longest-HR bonus`}
              className="text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border text-amber-300 border-amber-400/40 bg-amber-500/10"
            >
              🚀 Long-ball upside
            </span>
          )}
        {outcome && <OutcomeBadge outcome={outcome} iconOnly />}
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

      <LivePropTracker
        game={game}
        line={pick.line}
        outcome={liveOutcome}
        count={liveCount}
        unit={BATTER_UNIT[pick.market] ?? 'H'}
        batterLine={liveBatterLine}
      />

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

// The HR slot's "Lotto" boom pick (GET /api/lotto): NOT the most-likely homer, but a cold
// bottom-of-order bat with real raw power in a HR-friendly park/pitcher/weather spot — the case
// the model's own last-30 blend underweights. Age-blind, model-first (price optional). Rendered
// in the board's cyan batter style with the boom signals (order / barrel / slump / HR boost) and
// the server-built reasons, so it reads as one of the batter cards rather than a separate thing.
function BoomHrCard({
  boom,
  outcome,
  game,
  liveCount,
  liveOutcome,
}: {
  boom: BoomPick
  outcome?: PickOutcome
  game?: TodayGame
  liveCount?: number | null
  liveOutcome?: PickOutcome
}) {
  const meta = MARKET_META.hr
  return (
    <div className="rounded-xl border border-white/10 bg-[#0e1015] px-5 py-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border text-cyan-300 border-cyan-400/40 bg-cyan-500/10">
          {meta.chip}
        </span>
        <span
          title="A cold bat with real power the market is sleeping on — high variance by design"
          className="text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border text-amber-300 border-amber-400/40 bg-amber-500/10"
        >
          🎟 Lotto
        </span>
        {boom.hrDistanceFt != null && boom.hrDistanceFt >= LONG_BALL_UPSIDE_FT && (
          <span
            title={`Projects to carry ~${Math.round(boom.hrDistanceFt)} ft tonight — a real shot at the day's longest-HR bonus`}
            className="text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border text-amber-300 border-amber-400/40 bg-amber-500/10"
          >
            🚀 Long-ball upside
          </span>
        )}
        {outcome && <OutcomeBadge outcome={outcome} iconOnly />}
        <Link
          href={`/mlb/games/${boom.gameId}`}
          className="ml-auto font-mono text-xs text-zinc-500 hover:text-cyan-400 transition-colors"
        >
          {boom.matchup}
        </Link>
      </div>

      <div className="flex items-baseline justify-between gap-3">
        <Link
          href={`/mlb/players/${boom.playerId}`}
          className="text-base font-bold tracking-tight text-zinc-100 hover:text-cyan-300 transition-colors"
        >
          {boom.playerName}{' '}
          <span className="text-sm font-normal text-zinc-500">{meta.verb}</span>
        </Link>
        <span className="shrink-0 font-mono tabular-nums text-lg text-cyan-300">
          {pct(boom.pHr)}
        </span>
      </div>

      <div className="flex flex-wrap gap-x-4 gap-y-1">
        <Factor label="Order" value={ordinal(boom.lineupPosition)} />
        <Factor label="Barrel" value={pct(boom.barrelRate)} />
        <Factor label="Slump" value={`−${(boom.coldGap * 1000).toFixed(0)} xwOBA`} />
        <Factor label="HR boost" value={`×${boom.condBoost.toFixed(2)}`} />
      </div>

      <LivePropTracker
        game={game}
        line={0.5}
        outcome={liveOutcome}
        count={liveCount}
        unit="HR"
        batterLine={null}
      />

      <WhyDisclosure reasons={boom.reasons} />
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
// ambiguous. The headline number is the projection (expected Ks/outs/hits/ER); the
// Best pick row is the recommended side. In edge mode a chip shows the model-vs-line
// gap that earned the card; in volume-fallback mode a muted badge flags the mode.
function PitcherCard({
  pick,
  outcome,
  game,
  liveCount,
  liveOutcome,
  liveOuts,
}: {
  pick: PitcherPropPick
  outcome?: PickOutcome
  game?: TodayGame
  liveCount?: number | null
  liveOutcome?: PickOutcome
  liveOuts?: number | null
}) {
  const meta =
    PITCHER_MARKET_META[pick.market] ?? { chip: pick.market, unit: '', noun: pick.market }

  const reasons = buildPitcherReasons(pick)

  return (
    <div className="rounded-xl border border-amber-400/20 bg-[#0e1015] px-5 py-4 flex flex-col gap-3">
      <div className="flex items-center gap-2">
        <span className="text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border text-amber-300 border-amber-400/40 bg-amber-500/10">
          {meta.chip}
        </span>
        {pick.rankedBy === 'edge' && pick.edge != null ? (
          <span
            title={`Model ${pct(pick.bestProb ?? 0)} vs. the de-vigged book ${pct(pick.fairProb ?? 0)} on this side`}
            className="text-[10px] uppercase tracking-[0.12em] font-semibold px-1.5 py-0.5 rounded border text-emerald-300 border-emerald-400/40 bg-emerald-500/10"
          >
            +{(pick.edge * 100).toFixed(0)}% vs line
          </span>
        ) : (
          <span
            title="No odds for this market today — ranked by projected volume instead of edge"
            className="text-[10px] uppercase tracking-[0.12em] text-zinc-600"
          >
            Volume-ranked
          </span>
        )}
        {outcome && <OutcomeBadge outcome={outcome} iconOnly />}
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

      <LivePropTracker
        game={game}
        line={pick.bestLine}
        outcome={liveOutcome}
        count={liveCount}
        unit={meta.unit}
        outs={liveOuts}
      />

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


/**
 * Model-first prop board: one card per prop market with the model's most likely
 * batter and the reasoning. Unlike Model's Picks this never needs live odds — it
 * ranks by likelihood, not value, so it keeps working when the odds feed is off.
 */
export function PropBoard() {
  const { data, isPending, isError } = useQuery(propBoardQueryOptions())
  // The HR card is the "Lotto" boom pick when one qualifies (a cold slugger in a HR-friendly
  // spot); otherwise we fall back to the market's most-likely batter below.
  const { data: lotto } = useQuery(lottoQueryOptions())
  // Actual results overlay a ✓/✗ on the headline pick once its game is final.
  const { data: results } = useQuery(playerResultsQueryOptions())
  // Live game state (score/inning) for the in-progress tracker on each card.
  const { data: games } = useQuery(todayGamesQueryOptions())
  const gamesById = new Map<number, TodayGame>((games ?? []).map((g) => [g.gameId, g]))
  // Live player counts — poll only while a game is actually in progress; idle otherwise.
  const anyLive = (games ?? []).some(gameIsLive)
  const { data: liveResults } = useQuery({
    ...livePlayerResultsQueryOptions(),
    enabled: anyLive,
    refetchInterval: anyLive ? 30_000 : false,
  })
  const batterByKey = new Map<string, BatterResult>(
    (results?.batters ?? []).map((b) => [`${b.playerId}:${b.gameId}`, b]),
  )
  const pitcherByKey = new Map<string, PitcherResult>(
    (results?.pitchers ?? []).map((p) => [`${p.playerId}:${p.gameId}`, p]),
  )
  const liveBatterByKey = new Map<string, BatterResult>(
    (liveResults?.batters ?? []).map((b) => [`${b.playerId}:${b.gameId}`, b]),
  )
  const livePitcherByKey = new Map<string, PitcherResult>(
    (liveResults?.pitchers ?? []).map((p) => [`${p.playerId}:${p.gameId}`, p]),
  )

  function batterOutcome(pick: PropBoardPick): PickOutcome | undefined {
    const actual = batterActual(pick.market, batterByKey.get(`${pick.playerId}:${pick.gameId}`))
    if (actual === undefined) return undefined
    return propOutcome(actual, pick.line)
  }

  function pitcherOutcome(pick: PitcherPropPick): PickOutcome | undefined {
    const field = PITCHER_RESULT_FIELD[pick.market]
    if (!field) return undefined
    return overUnderOutcome(
      pick.bestSide,
      pick.bestLine,
      pitcherByKey.get(`${pick.pitcherId}:${pick.gameId}`)?.[field],
    )
  }

  // Live in-progress count + monotonic-safe live grade for the on-card tracker.
  function batterLiveCount(pick: PropBoardPick): number | null | undefined {
    return batterActual(pick.market, liveBatterByKey.get(`${pick.playerId}:${pick.gameId}`))
  }
  function pitcherLiveCount(pick: PitcherPropPick): number | null | undefined {
    const field = PITCHER_RESULT_FIELD[pick.market]
    return field ? livePitcherByKey.get(`${pick.pitcherId}:${pick.gameId}`)?.[field] : undefined
  }

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
          {data.picks.map((pick) => {
            // Swap the HR slot for the Lotto boom pick when one qualifies (same position/count,
            // so the grid layout is unchanged); fall back to the most-likely HR card otherwise.
            if (pick.market === 'hr' && lotto) {
              const key = `${lotto.playerId}:${lotto.gameId}`
              const boomLiveCount = liveBatterByKey.get(key)?.homeRuns
              return (
                <BoomHrCard
                  key="hr"
                  boom={lotto}
                  outcome={propOutcome(batterByKey.get(key)?.homeRuns, 0.5)}
                  game={gamesById.get(lotto.gameId)}
                  liveCount={boomLiveCount}
                  liveOutcome={liveCountOutcome('over', 0.5, boomLiveCount)}
                />
              )
            }
            const liveCount = batterLiveCount(pick)
            const liveBatter = liveBatterByKey.get(`${pick.playerId}:${pick.gameId}`)
            return (
              <PropCard
                key={pick.market}
                pick={pick}
                outcome={batterOutcome(pick)}
                game={gamesById.get(pick.gameId)}
                liveCount={liveCount}
                liveOutcome={liveCountOutcome('over', pick.line, liveCount)}
                liveBatterLine={
                  liveBatter ? { hits: liveBatter.hits, atBats: liveBatter.atBats } : null
                }
              />
            )
          })}
        </div>
      )}

      {!isPending && !isError && data.pitcherPicks.length > 0 && (
        <div className="mt-6">
          <p className={cn(microLabel, 'mb-2')}>
            {data.pitcherPicks.some((p) => p.rankedBy === 'edge')
              ? 'Pitcher props — biggest edge between the model and the book line'
              : 'Pitcher props — top starter by projected volume (no odds today)'}
          </p>
          <div
            className={cn(
              'grid gap-4',
              data.pitcherPicks.length === 1 && 'lg:max-w-xl',
              data.pitcherPicks.length >= 2 && 'lg:grid-cols-2',
            )}
          >
            {data.pitcherPicks.map((pick) => {
              const liveCount = pitcherLiveCount(pick)
              const livePitcher = livePitcherByKey.get(`${pick.pitcherId}:${pick.gameId}`)
              return (
                <PitcherCard
                  key={pick.market}
                  pick={pick}
                  outcome={pitcherOutcome(pick)}
                  game={gamesById.get(pick.gameId)}
                  liveCount={liveCount}
                  liveOutcome={liveCountOutcome(pick.bestSide, pick.bestLine, liveCount)}
                  liveOuts={livePitcher?.outs}
                />
              )
            })}
          </div>
        </div>
      )}
    </section>
  )
}
