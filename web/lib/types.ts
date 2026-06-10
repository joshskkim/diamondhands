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

/** Single-book (FanDuel) game-market odds shown on the today board. Fields may be null. */
export interface GameOddsSummary {
  book: string
  totalLine: number | null
  totalOverPrice: number | null
  totalUnderPrice: number | null
  homeMoneyline: number | null
  awayMoneyline: number | null
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
  odds: GameOddsSummary | null
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
  // Optional pitcher-own results — populated once the pitcher-stats API lands
  // (already stored in pitcher_arsenal: xwoba_against, whiff_rate, avg_velocity).
  xwobaAgainst?: number | null
  whiffRate?: number | null
  avgVelocity?: number | null
}

/**
 * A pitcher's season skill split by opposing batter handedness. Sourced from the
 * (not-yet-exposed) pitcher_skill table; optional until the API serves it.
 */
export interface PitcherSkillSplit {
  vsHand: string // 'L' | 'R'
  kRate: number | null
  bbRate: number | null
  xwobaAgainst: number | null
  hrPerPa: number | null
  battersFaced: number | null
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
  /** No-vig market probability for this side, or null if the market couldn't be de-vigged. */
  fairProb: number | null
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
  /** Raw side token: over/under for props & totals; home/away for moneyline/run line. */
  side: string
  selection: string
  line: number | null
  bestBook: string
  priceAmerican: number
  priceDecimal: number
  modelProb: number
  impliedProb: number
  /** No-vig market probability for this side; null if not de-vigged. */
  fairProb: number | null
  evPct: number
  playerId: number | null
  playerName: string | null
}

/**
 * GET /api/odds/hit-rates — Outlier-style "traffic light" for a batter prop market:
 * how often the player cleared the prop's line over recent games + the season.
 * Rates are 0..1 or null (no games in window); join to a BestPlay by playerId+market.
 */
export interface HitRate {
  playerId: number
  /** 'hit' | 'hr' */
  market: string
  line: number
  l5: number | null
  l10: number | null
  l20: number | null
  n20: number
  season: number | null
  nSeason: number
}

/** GET /api/odds/props — one batter prop over-price (BetRivers-first) for Best Bets. */
export interface BatterPropOdds {
  gameId: number
  playerId: number
  /** 'hit' | 'hr' */
  market: string
  line: number | null
  book: string
  priceAmerican: number | null
  priceDecimal: number | null
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

// ── Most Likely board (GET /api/most-likely) ─────────────────────────────────

/** Full-game total vs the consensus book line. */
export interface MostLikelyTotal {
  gameId: number
  matchup: string
  simTotal: number
  bookLine: number | null
  edge: number | null
  pOver: number | null
  lean: 'over' | 'under' | 'even' | null
}

/** First-inning run market (NRFI / YRFI). */
export interface MostLikelyNrfi {
  gameId: number
  matchup: string
  pYrfi: number
  pNrfi: number
  lean: 'NRFI' | 'YRFI'
  leanProb: number
}

/** First-five-innings (F5) market. */
export interface MostLikelyF5 {
  gameId: number
  matchup: string
  f5Total: number
  bookLine: number | null
  edge: number | null
  pOver: number | null
  favorite: string
  favoriteProb: number
  pTie: number
}

/** One player's entry on a prop leaderboard (value = probability or expected count). */
export interface PropLeader {
  playerId: number
  player: string
  team: string
  matchup: string
  value: number
}

export interface PropLeaders {
  hits: PropLeader[]
  homeRuns: PropLeader[]
  totalBases: PropLeader[]
  strikeouts: PropLeader[]
}

/** GET /api/most-likely */
export interface MostLikely {
  date: string
  totals: MostLikelyTotal[]
  nrfi: MostLikelyNrfi[]
  f5: MostLikelyF5[]
  props: PropLeaders
}
