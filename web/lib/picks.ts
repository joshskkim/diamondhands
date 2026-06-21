import type { ModelPickResult } from './types'
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
