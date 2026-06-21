import type { BestPlay, ModelPickResult, TodayGame } from './types'
import { MARKET_LABEL, teamForSide } from './odds'

/** The minimal shape a pick title needs — satisfied by both BestPlay (live board)
 *  and ModelPickResult (persisted, graded). */
export interface PickLike {
  market: string
  side: string
  line?: number | null
  playerName?: string | null
  matchup: string
}

/** Human title for a pick, e.g. "Over 8.5 total runs" / "Aaron Judge over 1.5 hits".
 *  Shared by Model's Picks (live) and the Recent-results recap. */
export function pickTitle(p: PickLike): string {
  const sideWord = p.side === 'over' ? 'Over' : p.side === 'under' ? 'Under' : null
  switch (p.market) {
    case 'moneyline':
      return `${teamForSide(p.matchup, p.side)} moneyline`
    case 'run_line':
      return `${teamForSide(p.matchup, p.side)} ${
        p.line != null && p.line > 0 ? `+${p.line}` : p.line
      } run line`
    case 'total':
      return `${sideWord} ${p.line} total runs`
    case 'hit':
      return `${p.playerName} ${sideWord?.toLowerCase()} ${p.line} hits`
    case 'hr':
      return `${p.playerName} ${sideWord?.toLowerCase()} ${p.line} home runs`
    default:
      return `${p.playerName ?? p.matchup} ${sideWord ?? p.side} ${p.line ?? ''} ${
        MARKET_LABEL[p.market] ?? p.market
      }`.trim()
  }
}

/** Identity for matching a live board pick to its persisted/graded counterpart. */
export function pickKey(p: {
  gameId: number
  market: string
  side: string
  line: number | null
  playerId: number | null
}): string {
  return `${p.gameId}|${p.market}|${p.side}|${p.line ?? ''}|${p.playerId ?? ''}`
}

export type PickOutcome = 'won' | 'lost' | 'push' | 'pending'

/** ✓/✗/push for the projected favorite given the final score (undefined while unplayed). */
export function favoriteOutcome(
  favHome: boolean,
  finalHome: number | null,
  finalAway: number | null,
): PickOutcome | undefined {
  if (finalHome == null || finalAway == null) return undefined
  if (finalHome === finalAway) return 'push'
  const favWon = favHome ? finalHome > finalAway : finalAway > finalHome
  return favWon ? 'won' : 'lost'
}

/** Graded outcome of a persisted pick: pending until score-picks settles it. */
export function pickOutcome(p: Pick<ModelPickResult, 'scored' | 'won'>): PickOutcome {
  if (!p.scored) return 'pending'
  if (p.won == null) return 'push'
  return p.won ? 'won' : 'lost'
}

// ── live, same-day grading from actual results (mirrors favoriteOutcome) ─────────
// These power the ✓/✗ badges on the Prop Board, Sim Signals, and Model's Picks. Each
// returns undefined while the relevant game (or stat) hasn't landed, so nothing shows
// pre-final — exactly like the projected-favorites marker.

/** A generic over/under line graded against an actual value (push on the line). */
export function overUnderOutcome(
  side: 'over' | 'under' | null,
  line: number | null,
  actual: number | null | undefined,
): PickOutcome | undefined {
  if (side == null || line == null || actual == null) return undefined
  if (actual === line) return 'push'
  return (side === 'over') === (actual > line) ? 'won' : 'lost'
}

/** A ≥1 batter prop (hit/HR/K/BB, 0.5 line, always the "over"): did the player clear it. */
export function propOutcome(
  actual: number | null | undefined,
  line = 0.5,
): PickOutcome | undefined {
  if (actual == null) return undefined
  return actual > line ? 'won' : 'lost'
}

/** A sim totals lean (over/under the book line) graded against the final total. */
export function totalLeanOutcome(
  lean: 'over' | 'under' | 'even' | null,
  bookLine: number | null,
  finalHome: number | null,
  finalAway: number | null,
): PickOutcome | undefined {
  if (bookLine == null || finalHome == null || finalAway == null) return undefined
  if (lean !== 'over' && lean !== 'under') return undefined
  const actual = finalHome + finalAway
  if (actual === bookLine) return 'push'
  return (lean === 'over') === (actual > bookLine) ? 'won' : 'lost'
}

/** A run-line lean (favorite covers -1.5): did the favorite win by 2+ (no push on a half-run). */
export function runLineOutcome(
  favHome: boolean,
  finalHome: number | null,
  finalAway: number | null,
): PickOutcome | undefined {
  if (finalHome == null || finalAway == null) return undefined
  const margin = favHome ? finalHome - finalAway : finalAway - finalHome
  return margin >= 2 ? 'won' : 'lost'
}

/** An NRFI/YRFI lean graded against actual first-inning runs. */
export function nrfiOutcome(
  lean: 'NRFI' | 'YRFI',
  homeFirst: number | null,
  awayFirst: number | null,
): PickOutcome | undefined {
  if (homeFirst == null || awayFirst == null) return undefined
  const yrfi = homeFirst + awayFirst > 0
  return (lean === 'YRFI') === yrfi ? 'won' : 'lost'
}

/** A Model's Pick graded live: game markets from final scores, HR from batter results.
 *  `hrByKey` is keyed `${playerId}:${gameId}` → the player's home-run count. */
export function modelPlayOutcome(
  play: BestPlay,
  game: Pick<TodayGame, 'finalHomeScore' | 'finalAwayScore'> | undefined,
  hrByKey: Map<string, number | null>,
): PickOutcome | undefined {
  const home = game?.finalHomeScore
  const away = game?.finalAwayScore
  switch (play.market) {
    case 'total':
      return overUnderOutcome(
        play.side as 'over' | 'under',
        play.line,
        home == null || away == null ? null : home + away,
      )
    case 'moneyline': {
      if (home == null || away == null) return undefined
      if (home === away) return 'push'
      return (play.side === 'home') === (home > away) ? 'won' : 'lost'
    }
    case 'run_line': {
      if (home == null || away == null || play.line == null) return undefined
      const margin = play.side === 'home' ? home - away : away - home
      const adj = margin + play.line
      if (adj === 0) return 'push'
      return adj > 0 ? 'won' : 'lost'
    }
    case 'hr':
      if (play.playerId == null) return undefined
      return overUnderOutcome(
        play.side as 'over' | 'under',
        play.line,
        hrByKey.get(`${play.playerId}:${play.gameId}`),
      )
    default:
      return undefined
  }
}

/** A YYYY-MM-DD date string in US Eastern (the league/slate timezone), offset by
 *  `offsetDays` (e.g. -1 for yesterday's slate). Matches the ingester's slate dates. */
export function easternDateStr(offsetDays = 0): string {
  const parts = new Intl.DateTimeFormat('en-CA', {
    timeZone: 'America/New_York',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  }).formatToParts(new Date())
  const get = (t: string) => parts.find((p) => p.type === t)!.value
  const d = new Date(`${get('year')}-${get('month')}-${get('day')}T00:00:00Z`)
  d.setUTCDate(d.getUTCDate() + offsetDays)
  return d.toISOString().slice(0, 10)
}
