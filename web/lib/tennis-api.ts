import { queryOptions } from '@tanstack/react-query'

// Self-contained fetch helper (apiGet in lib/api.ts is module-private). Same
// base URL + credentials behaviour.
const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8080'

async function get<T>(path: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, { credentials: 'include' })
  if (!res.ok) throw new Error(`API error ${res.status}: ${path}`)
  return res.json() as Promise<T>
}

// ── Types (mirror the API records) ───────────────────────────────────────────

export type TennisPlayer = { id: string; name: string; country: string | null }

export type TennisEv = {
  side: string
  playerName: string
  bookmaker: string | null
  priceAmerican: number | null
  priceDecimal: number | null
  modelProb: number
  fairProb: number
  edgePct: number
  evPct: number
} | null

export type TennisMatch = {
  matchId: number
  startTimeUtc: string | null
  surface: string | null
  bestOf: number | null
  playerA: TennisPlayer
  playerB: TennisPlayer
  pWinA: number | null
  expTotalGames: number | null
  bestPlay: TennisEv
  status: string
}

export type TennisQuote = {
  side: string
  bookmaker: string
  priceAmerican: number
  priceDecimal: number
  impliedProb: number
}

export type TennisTotalEv = {
  side: string
  line: number
  bookmaker: string | null
  priceAmerican: number | null
  priceDecimal: number | null
  modelProb: number
  fairProb: number
  edgePct: number
  evPct: number
} | null

export type TennisMatchDetail = {
  matchId: number
  startTimeUtc: string | null
  surface: string | null
  bestOf: number | null
  status: string
  playerA: TennisPlayer
  playerB: TennisPlayer
  eloA: number | null
  eloB: number | null
  pWinA: number | null
  pServeA: number | null
  pServeB: number | null
  expTotalGames: number | null
  probStraightSets: number | null
  quotes: TennisQuote[]
  bestPlay: TennisEv
  bestTotalPlay: TennisTotalEv
}

export type TennisRanking = {
  rank: number
  player: TennisPlayer
  elo: number | null
  serveSkill: number | null
  returnSkill: number | null
  matches: number | null
}

export type TennisAccuracyPoint = {
  period: string
  n: number
  brier: number | null
  baselineBrier: number | null
  ece: number | null
}

export type TennisCalibrationBucket = {
  lo: number
  hi: number
  n: number
  predictedMean: number
  actualRate: number
}

export type TennisAccuracy = {
  modelVersion: string | null
  surface: string
  series: TennisAccuracyPoint[]
  calibration: TennisCalibrationBucket[]
}

// ── Query options ────────────────────────────────────────────────────────────

export function tennisMatchesQueryOptions() {
  return queryOptions({
    queryKey: ['tennis', 'matches'] as const,
    queryFn: () => get<TennisMatch[]>('/api/tennis/matches/today'),
  })
}

export function tennisMatchDetailQueryOptions(matchId: number) {
  return queryOptions({
    queryKey: ['tennis', 'match', matchId] as const,
    queryFn: () => get<TennisMatchDetail>(`/api/tennis/matches/${matchId}`),
    enabled: matchId > 0,
  })
}

export function tennisRankingsQueryOptions(surface: string) {
  return queryOptions({
    queryKey: ['tennis', 'rankings', surface] as const,
    queryFn: () => get<TennisRanking[]>(`/api/tennis/rankings?surface=${surface}&limit=100`),
  })
}

export function tennisAccuracyQueryOptions(surface: string) {
  return queryOptions({
    queryKey: ['tennis', 'accuracy', surface] as const,
    queryFn: () => get<TennisAccuracy>(`/api/tennis/accuracy?surface=${surface}`),
  })
}
