import type { ModelPickResult, TodayGame } from './types'
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

export type PickOutcome = 'won' | 'lost' | 'push' | 'pending' | 'live'

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

// ── live, in-progress trackers (monotonic-safe early settlement) ─────────────────
// These run off the streamed games.live_* state while a game is being played. They only
// ever settle the direction that CAN'T reverse (a total can only climb), so an under can
// flip to 'lost' the instant the line is exceeded but never to 'won' before Final — the
// winning side is left to the Final helpers above. Otherwise they return 'live' so the
// board can show an in-progress indicator instead of a clock.

/** Live grade of a total against the running score. `over` settles 'won' once the line is
 *  cleared; `under` settles 'lost' once it's exceeded; otherwise 'live'. Returns undefined
 *  when there's no live total (or the game is final — let the Final helper grade it). */
export function liveTotalOutcome(
  side: 'over' | 'under' | null,
  line: number | null,
  liveTotal: number | null | undefined,
  isFinal: boolean,
): PickOutcome | undefined {
  if (isFinal || side == null || line == null || liveTotal == null) return undefined
  if (liveTotal > line) return side === 'over' ? 'won' : 'lost'
  return 'live'
}

/** Live grade of a player count (pitcher K/outs/ER/H, batter H/HR) against its line.
 *  Monotonic-safe like liveTotalOutcome: `over` settles 'won' once the count clears the
 *  line, `under` settles 'lost' once it's exceeded; otherwise 'live'. A count can only
 *  climb, so the other direction is never settled early. Returns undefined with no count. */
export function liveCountOutcome(
  side: 'over' | 'under' | null,
  line: number | null,
  actual: number | null | undefined,
): PickOutcome | undefined {
  if (side == null || line == null || actual == null) return undefined
  if (actual > line) return side === 'over' ? 'won' : 'lost'
  return 'live'
}

/** Projected 9-inning total from the current running total and inning, for an on-pace
 *  read. Returns null until at least a half-inning has been played. */
export function liveTotalPace(
  liveTotal: number | null | undefined,
  currentInning: number | null | undefined,
  isTop: boolean | null | undefined,
): number | null {
  if (liveTotal == null || currentInning == null || currentInning < 1) return null
  const elapsed = currentInning - 1 + (isTop ? 0.5 : 1)
  if (elapsed < 0.5) return null
  return (liveTotal / elapsed) * 9
}

/** Live signed margin from the favorite's perspective (positive = favorite ahead), for a
 *  run-line "covering / not covering" read. Final grading stays with runLineOutcome. */
export function liveRunLineMargin(
  favHome: boolean,
  liveHome: number | null | undefined,
  liveAway: number | null | undefined,
): number | null {
  if (liveHome == null || liveAway == null) return null
  return favHome ? liveHome - liveAway : liveAway - liveHome
}

/** The fields live-grading needs — satisfied by both BestPlay (live board) and
 *  ModelPickResult (persisted, for earlier/bumped picks not yet settled). */
export interface GradablePlay {
  market: string
  side: string
  line: number | null
  playerId: number | null
  gameId: number
}

/** The game-state fields modelPlayOutcome reads — Final score for grading plus the live
 *  state for in-progress trackers. Satisfied by TodayGame. */
type GradableGame = Pick<
  TodayGame,
  | 'finalHomeScore'
  | 'finalAwayScore'
  | 'liveHomeScore'
  | 'liveAwayScore'
  | 'status'
>

/** A Model's Pick graded live: game markets settle from the Final score, and while a game
 *  is in progress they early-settle the monotonic-safe direction (a total can only climb)
 *  or show a 'live' indicator. HR (player) markets stay pending until Final — that's a
 *  later phase. `hrByKey` is keyed `${playerId}:${gameId}` → the player's home-run count. */
export function modelPlayOutcome(
  play: GradablePlay,
  game: GradableGame | undefined,
  hrByKey: Map<string, number | null>,
): PickOutcome | undefined {
  const home = game?.finalHomeScore
  const away = game?.finalAwayScore
  const isFinal = home != null && away != null
  const liveHome = game?.liveHomeScore
  const liveAway = game?.liveAwayScore
  const liveTotal = liveHome != null && liveAway != null ? liveHome + liveAway : null
  const isLive = !isFinal && (game?.status === 'Live' || liveTotal != null)
  switch (play.market) {
    case 'total':
      return (
        overUnderOutcome(
          play.side as 'over' | 'under',
          play.line,
          isFinal ? home! + away! : null,
        ) ?? liveTotalOutcome(play.side as 'over' | 'under', play.line, liveTotal, isFinal)
      )
    case 'moneyline': {
      if (isFinal) {
        if (home === away) return 'push'
        return (play.side === 'home') === (home! > away!) ? 'won' : 'lost'
      }
      return isLive ? 'live' : undefined
    }
    case 'run_line': {
      if (play.line == null) return undefined
      if (isFinal) {
        const margin = play.side === 'home' ? home! - away! : away! - home!
        const adj = margin + play.line
        if (adj === 0) return 'push'
        return adj > 0 ? 'won' : 'lost'
      }
      return isLive ? 'live' : undefined
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
