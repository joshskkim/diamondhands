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
  /** MLB detailedState (Postponed / Suspended / Cancelled / Delayed …) when it differs
   *  from the coarse `status`; null for a normal game. A dead game keeps its slate card
   *  (badged) but its projections/picks are pulled off every board. */
  detailedStatus: string | null
  /** Final score once the game is over (null while scheduled / in progress). */
  finalHomeScore: number | null
  finalAwayScore: number | null
  /** Runs per side in the 1st inning, set once the 1st completes (null otherwise) —
   *  drives the NRFI/YRFI hit/miss marker on the Sim Signals board. */
  finalHomeFirstInningRuns: number | null
  finalAwayFirstInningRuns: number | null
}

/** GET /api/model-picks — a persisted Model's Pick with its graded outcome. */
export interface ModelPickResult {
  slateDate: string
  /** Board order among active picks; null for an earlier/bumped pick. */
  rank: number | null
  gameId: number
  market: string
  side: string
  line: number | null
  playerId: number | null
  playerName: string | null
  matchup: string
  modelProb: number
  fairProb: number
  edge: number
  evPct: number
  priceAmerican: number
  book: string | null
  strong: boolean
  resultValue: number | null
  /** true = hit, false = miss, null = push/void or not yet graded. */
  won: boolean | null
  /** true once score-picks has settled it (won may still be null on a push). */
  scored: boolean
  /** false once a better late pick displaced this one from the top set (still graded). */
  active: boolean
  /** ISO-8601 (UTC) instant the pick first made the board — its line is locked here. */
  firstShownAt: string | null
  /** ISO-8601 (UTC) instant it was displaced, or null if it never was. */
  bumpedAt: string | null
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
  /** Opposing-team defense hit-suppression factor (hit side only; 1 = neutral). */
  defense: number
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

/** One starting pitcher's full breakdown for the game view's Pitchers tab. */
export interface PitcherDetail {
  id: number
  name: string
  throws: string | null
  teamAbbr: string
  /** Pitch mix vs both batter hands (collapsed by type in the UI). */
  arsenal: PitchArsenal[]
  /** Season K%/BB%/xwOBA-against/HR-per-PA splits vs LHB / RHB. */
  skill: PitcherSkillSplit[]
}

/** The two probable starters: `home` = the home team's starter. */
export interface GamePitchers {
  home: PitcherDetail | null
  away: PitcherDetail | null
}

/** GET /api/games/:gameId/projections */
export interface GameProjections {
  gameId: number
  home: TeamBatters
  away: TeamBatters
  /** Null when neither probable starter is known yet. */
  pitchers: GamePitchers | null
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

/** One bookmaker's posted price for a prop selection. */
export interface BookQuote {
  book: string
  priceAmerican: number
  priceDecimal: number
}

/**
 * GET /api/odds/line-shop — per-selection book ladder for line shopping.
 * `key` = "gameId:playerId:market:side:line" (line trailing-zeros stripped), matching
 * a BestPlay row built from the same fields. `quotes` is sorted best-price-first.
 */
export interface LineShop {
  key: string
  quotes: BookQuote[]
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

/**
 * GET /api/props/board — the model's most likely batter for one prop market
 * (all 0.5 lines), with the factors that explain the number. Price fields are the
 * best *cached* over-price and are null whenever odds haven't been pulled; the
 * pick stands on the model alone.
 */
export interface PropBoardPick {
  /** 'hit' | 'hr' | 'k' */
  market: string
  line: number
  gameId: number
  matchup: string
  playerId: number
  player: string
  team: string
  lineupPosition: number | null
  lineupConfirmed: boolean | null
  expectedPa: number | null
  /** Displayed probability: model shrunk toward the player's season clear rate. */
  prob: number
  /** Raw model probability before the empirical-rate shrinkage. */
  probModel: number
  opposingPitcherId: number | null
  opposingPitcher: string | null
  /** 'matchup' | 'overall' | 'league_avg' */
  pitcherDataQuality: string | null
  /** Opposing starter's season walk rate (per PA, BF-weighted across handedness) — the
   *  walk card's driver. Null for a TBD starter or one with no skill row. */
  opposingPitcherBbRate: number | null
  /** Opposing starter's season K rate (per PA) — lets the walk card flag a contact arm. */
  opposingPitcherKRate: number | null
  matchupXwoba: number | null
  /** 'matchup' | 'fallback_overall' */
  matchupQuality: string | null
  adjPark: number | null
  adjPitcher: number | null
  adjWeather: number | null
  adjDefense: number | null
  stadium: string | null
  /** 'L' | 'R' | 'S' — batting side (server defaults unknown to 'R'). */
  bats: string | null
  /** Share of balls in play hit to the batter's pull side (current season, ≥50 BIP). */
  pullPct: number | null
  fbPct: number | null
  avgLaunchSpeed: number | null
  /** Fence distance/wall height on the batter's pull side; null for switch hitters. */
  pullFenceFt: number | null
  pullWallFt: number | null
  /** Projected HR carry (ft) in this game's park/weather — the long-ball-upside axis on the
   *  HR card. Orthogonal to the HR likelihood; null when the batter has no HR-distance sample. */
  hrDistanceFt: number | null
  rateL10: number | null
  rateSeason: number | null
  nSeason: number | null
  bestBook: string | null
  priceAmerican: number | null
  priceDecimal: number | null
  evPct: number | null
  /** Next two batters by the same blended ranking — honorable mentions. */
  runnersUp: PropBoardRunnerUp[]
}

/** An honorable mention on a prop card: name + blended probability, no reasoning. */
export interface PropBoardRunnerUp {
  playerId: number
  player: string
  team: string
  prob: number
}

/** One over-threshold from a pitcher's workload distribution: P(over `line`). */
export interface PitcherThreshold {
  line: number
  prob: number
}

/** An honorable-mention pitcher: same expected-volume ranking, no distribution. */
export interface PitcherRunnerUp {
  pitcherId: number
  pitcher: string
  team: string
  expectedValue: number
}

/**
 * The model's headline starting pitcher for one pitcher-prop market, ranked by
 * EXPECTED VOLUME (expected Ks / outs) rather than P(clear) — pitcher lines vary by
 * arm, so ranking on clear-probability would surface soft-tossers, not aces. Odds
 * fields are the best cached over-price and are null when odds haven't been pulled.
 */
export interface PitcherPropPick {
  /** 'pitcher_k' | 'pitcher_outs' | 'pitcher_hits_allowed' | 'pitcher_earned_runs' */
  market: string
  gameId: number
  matchup: string
  pitcherId: number
  pitcher: string
  team: string
  /** Team (lineup) the starter faces. */
  opponent: string
  expectedValue: number
  expectedIp: number | null
  distribution: PitcherThreshold[]
  /** The single recommended pick: side the model leans at the most relevant line. */
  bestLine: number | null
  bestSide: 'over' | 'under' | null
  bestProb: number | null
  /** Best cached price + EV for the recommended side at bestLine (null when no odds). */
  bookLine: number | null
  bestBook: string | null
  priceAmerican: number | null
  evPct: number | null
  /** Reasoning drivers (null when skill rows are absent): the pitcher's own BF-weighted
   *  profile and the opposing lineup's PA-weighted K rate / xwOBA. */
  pitcherKRate: number | null
  pitcherBbRate: number | null
  pitcherXwobaAgainst: number | null
  pitcherHrPerPa: number | null
  opponentKRate: number | null
  opponentXwoba: number | null
  /** The starter's top pitches by usage (empty when no arsenal snapshot). */
  arsenal: PitcherArsenalPitch[]
  runnersUp: PitcherRunnerUp[]
}

/** One pitch in a starter's mix for the prop-board reasoning. */
export interface PitcherArsenalPitch {
  pitchType: string
  usageRate: number | null
  whiffRate: number | null
  avgVelocity: number | null
}

/** GET /api/props/board — model-first prop board for a slate. */
export interface PropBoard {
  date: string
  battersConsidered: number
  picks: PropBoardPick[]
  pitcherPicks: PitcherPropPick[]
}

/** One 10° spray sector: balls in play, homers, average Statcast hit distance. */
export interface SprayBin {
  /** 0 = hugs the LF foul line … 8 = hugs the RF line (field-absolute). */
  bin: number
  bip: number
  hr: number
  avgDistanceFt: number | null
}

/**
 * GET /api/players/:playerId/spray — spray-direction bins for the hot-zone
 * visual. Empty bins = the player is below the 50-BIP aggregation gate.
 */
export interface PlayerSpray {
  playerId: number
  season: number
  bats: string | null
  totalBip: number
  bins: SprayBin[]
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

/** One day's accuracy snapshot for a market (binary metrics null for total_runs). */
export interface AccuracyPoint {
  date: string
  n: number
  brier: number | null
  baselineBrier: number | null
  ece: number | null
  /** Log-loss: proper scoring rule, sharper than Brier on rare events. */
  logLoss: number | null
  /** Sharpness = variance of predicted probs; read with ece ("sharpness subject to calibration"). */
  sharpness: number | null
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

// ── Track Record (GET /api/track-record) ─────────────────────────────────────

/** Win/loss record + units/ROI for a slice of graded picks (overall, a market, or a tier). */
export interface RecordSummary {
  label: string
  n: number // settled non-void picks (wins + losses + pushes)
  wins: number
  losses: number
  pushes: number
  winPct: number // over decided picks only
  units: number // net units at flat 1u stakes
  roiPct: number
}

/** One point on the cumulative-units equity curve. */
export interface EquityPoint {
  date: string
  cumUnits: number
  cumWins: number
  cumLosses: number
}

/**
 * GET /api/track-record — how the published Model's Picks actually performed.
 * pickBrier scores only this +EV-selected sample, NOT the whole model (that's /api/accuracy).
 */
export interface TrackRecord {
  days: number
  asOf: string | null
  /** Distinct model versions the record spans (disclosed, not filtered). */
  modelVersions: string[]
  overall: RecordSummary
  byMarket: RecordSummary[]
  byTier: RecordSummary[]
  equity: EquityPoint[]
  pickBrier: number | null
  /** CLV sample size: settled picks for which a closing quote was found. Null until any CLV. */
  clvN: number | null
  /** Share of clvN with positive closing-line value (we beat the close). */
  clvRate: number | null
  /** Mean CLV (de-vigged probability points beaten) over clvN. */
  avgClv: number | null
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

/** Full-game run-line (±1.5 spread) lean from the simulator's joint run distribution. */
export interface MostLikelyRunLine {
  gameId: number
  matchup: string
  /** Team abbr laying the -1.5. */
  favorite: string
  /** That side's simulated probability of covering -1.5. */
  coverProb: number
  /** -1.5 when run-line odds exist, else null. */
  bookLine: number | null
  /** coverProb minus the no-vig book implied for the same side; null without odds. */
  edge: number | null
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
  runLine: MostLikelyRunLine[]
  props: PropLeaders
}

/** A batter's actual line for one finished game (grades prop-board batter picks). */
export interface BatterResult {
  playerId: number
  gameId: number
  hits: number | null
  homeRuns: number | null
  strikeouts: number | null
  walks: number | null
}

/** A starter's actual line for one finished game (grades pitcher prop picks). */
export interface PitcherResult {
  playerId: number
  gameId: number
  strikeouts: number | null
  outs: number | null
  hitsAllowed: number | null
  earnedRuns: number | null
}

/** GET /api/results/players — actual per-player results for a slate. */
export interface PlayerResults {
  date: string
  batters: BatterResult[]
  pitchers: PitcherResult[]
}
