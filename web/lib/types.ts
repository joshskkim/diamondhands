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

export interface BatterProjection {
  player: BatterPlayer
  opposingPitcher: Pitcher
  expectedPa: number
  probabilities: Probabilities
  expectedHits: number
  expectedTotalBases: number
  adjustments: Adjustments
  pitcherDataQuality: string | null
}

export interface TeamBatters {
  teamAbbr: string
  batters: BatterProjection[]
}

/** GET /api/games/:gameId/projections */
export interface GameProjections {
  gameId: number
  home: TeamBatters
  away: TeamBatters
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
