/** Shared team reference on slate cards. */
export interface Team {
  id: number
  abbr: string
  name: string
}

export interface Stadium {
  name: string
  isDome: boolean
}

export interface Weather {
  tempF: number | null
  windMph: number | null
  windDirDeg: number | null
}

export interface Probable {
  id: number
  name: string
}

export interface Probables {
  home: Probable | null
  away: Probable | null
}

export interface ProjectionSummary {
  expectedHomeRuns: number
  expectedAwayRuns: number
  expectedTotal: number
  projectedAt: string
}

/** GET /api/games/today */
export interface TodayGame {
  gameId: number
  startTimeUtc: string
  home: Team
  away: Team
  stadium: Stadium
  weather: Weather
  probables: Probables
  projection: ProjectionSummary | null
  status: string
}

export interface BatterPlayer {
  id: number
  name: string
  bats: string
  position: string
}

export interface Pitcher {
  id: number
  name: string
  throws: string
}

export interface Probabilities {
  hit1plus: number
  hit2plus: number
  hr: number
  k1plus: number
}

export interface Adjustments {
  park: number
  pitcher: number
  weatherHr: number
  weatherHit: number
}

/** One pitch type in the opposing pitcher's arsenal vs this batter's hand. */
export interface PitchArsenal {
  pitchType: string
  usageRate: number | null
  leagueXwoba: number | null
}

/** The batter's regressed xwOBA vs one of the pitcher's pitch types, with signed edge. */
export interface BatterVsArsenal {
  pitchType: string
  xwobaRegressed: number | null
  pitchesSeen: number | null
  /** Signed string vs league baseline, e.g. "+0.064" / "-0.067". */
  edge: string | null
}

export interface BatterProjection {
  player: BatterPlayer
  opposingPitcher: Pitcher
  expectedPa: number
  probabilities: Probabilities
  expectedHits: number
  expectedTotalBases: number
  adjustments: Adjustments
  pitcherDataQuality: string | null
  /** 1-9 when the lineup is confirmed, else null (projected lineup). */
  lineupPosition: number | null
  lineupConfirmed: boolean | null
  /** Usage-weighted, pitch-type-regressed xwOBA that drove the hit rate (v2.1). */
  matchupXwoba: number | null
  /** 'matchup' when built from the pitcher's arsenal, else 'fallback_overall'. */
  matchupQuality: string | null
  pitcherArsenal: PitchArsenal[] | null
  /** Sorted by the pitcher's usage of each pitch type, descending. */
  batterVsArsenal: BatterVsArsenal[] | null
}

/** GET /api/leaderboards/pitch-types */
export interface PitchTypeRef {
  code: string
  name: string
}

/** GET /api/leaderboards/pitch-type */
export interface PitchTypeLeaderboardEntry {
  player: { id: number; name: string; teamAbbr: string }
  opposingPitcher: Pitcher
  pitchTypeUsage: number
  batterXwoba: number
  leagueXwoba: number
  edge: number
  pitchesSeen: number
}

export interface TeamBatters {
  teamAbbr: string
  /** True when this side's batting order came from a confirmed lineup. */
  lineupConfirmed: boolean
  batters: BatterProjection[]
}

/** GET /api/games/:gameId/projections */
export interface GameProjections {
  gameId: number
  home: TeamBatters
  away: TeamBatters
}

/**
 * A single batter's projection flattened with its game context, for use in the
 * home "Today's Board" pick leaderboards. Additive helper type — derived
 * entirely from existing endpoints (no backend changes).
 */
export interface FlatBatterPick {
  batter: BatterProjection
  gameId: number
  teamAbbr: string
  opponentAbbr: string
  opposingPitcherName: string
  opposingPitcherThrows: string
  startTimeUtc: string
  /** True when this batter's lineup slot came from a confirmed lineup. */
  lineupConfirmed: boolean
}

// ── Sportsbook odds ───────────────────────────────────────────────────────

/** One bookmaker's price for a single line. */
export interface BookPrice {
  book: string
  priceAmerican: number
  priceDecimal: number
  impliedProb: number
}

/**
 * Best available price for one side of one line, plus every book's price and our
 * model's view. modelProb/evPct are null for markets we don't model (pitcher props).
 */
export interface LineQuote {
  side: string
  line: number | null
  bestBook: string | null
  priceAmerican: number | null
  priceDecimal: number | null
  impliedProb: number | null
  modelProb: number | null
  evPct: number | null
  books: BookPrice[]
}

export interface GameMarket {
  /** moneyline | run_line | total */
  market: string
  quotes: LineQuote[]
}

export interface PropMarket {
  player: BatterPlayer
  /** hit | hr | pitcher_k | pitcher_outs */
  market: string
  line: number | null
  over: LineQuote | null
  under: LineQuote | null
}

/** GET /api/games/:gameId/odds */
export interface GameOdds {
  gameId: number
  hasOdds: boolean
  game: GameMarket[]
  props: PropMarket[]
}

/** GET /api/odds/best — one model-edged selection on the Best Lines board. */
export interface BestPlay {
  gameId: number
  matchup: string
  market: string
  selection: string
  line: number | null
  bestBook: string
  priceAmerican: number
  priceDecimal: number
  modelProb: number
  impliedProb: number
  evPct: number
  playerId: number | null
  playerName: string | null
}

/** GET /api/players/:playerId */
export interface PlayerDetail {
  id: number
  fullName: string
  teamId: number | null
  teamAbbr: string | null
  position: string | null
  bats: string | null
  throwsHand: string | null
}

/** GET /api/players/:playerId/recent */
export interface RecentStat {
  gameDate: string
  opp: string
  isHome: boolean
  pa: number
  hits: number
  hr: number
  k: number
  xwoba: number | null
}

/** One decile of a calibration curve: predicted bin vs realized rate. */
export interface CalibrationBucket {
  lo: number
  hi: number
  n: number
  predictedMean: number
  actualRate: number
}

/** One day's accuracy snapshot for a market (brier/baseline/ece null for total_runs). */
export interface AccuracyPoint {
  date: string
  n: number
  brier: number | null
  baselineBrier: number | null
  ece: number | null
}

/** Rolling accuracy for one market + its latest calibration curve. */
export interface MarketAccuracy {
  market: string
  series: AccuracyPoint[]
  calibration: CalibrationBucket[]
  mae: number | null
}

/** GET /api/accuracy */
export interface AccuracyResponse {
  days: number
  modelVersion: string | null
  markets: MarketAccuracy[]
}
