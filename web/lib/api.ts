import { queryOptions } from '@tanstack/react-query'
import type {
  AccuracyResponse,
  BestPlay,
  FlatBatterPick,
  GameOdds,
  GameProjections,
  PitcherSkillSplit,
  PitchTypeLeaderboardEntry,
  PitchTypeRef,
  PlayerDetail,
  TeamBatters,
  RecentStat,
  TodayGame,
} from './types'

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8080'

export class ApiError extends Error {
  readonly status: number
  readonly path: string

  constructor(status: number, path: string) {
    super(`API error ${status}: ${path}`)
    this.name = 'ApiError'
    this.status = status
    this.path = path
  }
}

async function apiGet<T>(path: string): Promise<T> {
  // credentials:'include' so the session cookie rides along (no-op for server fetches).
  const res = await fetch(`${API_BASE}${path}`, { credentials: 'include' })
  if (!res.ok) throw new ApiError(res.status, path)
  return res.json() as Promise<T>
}

async function apiPost<T>(path: string, body: unknown): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    method: 'POST',
    credentials: 'include',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  })
  if (!res.ok) throw new ApiError(res.status, path)
  return (res.status === 204 ? undefined : await res.json()) as T
}

// ── Auth ─────────────────────────────────────────────────────────────────────

export type AuthUser = { id: number; email: string; handle: string }

/** Current user, or null when not signed in (API returns 401). */
export async function fetchMe(): Promise<AuthUser | null> {
  const res = await fetch(`${API_BASE}/api/auth/me`, { credentials: 'include' })
  if (res.status === 401) return null
  if (!res.ok) throw new ApiError(res.status, '/api/auth/me')
  return res.json() as Promise<AuthUser>
}

export function signUp(input: {
  email: string
  handle: string
  password: string
}): Promise<AuthUser> {
  return apiPost<AuthUser>('/api/auth/signup', input)
}

export function signIn(input: { email: string; password: string }): Promise<AuthUser> {
  return apiPost<AuthUser>('/api/auth/signin', input)
}

export function signOut(): Promise<void> {
  return apiPost<void>('/api/auth/signout', {})
}

// ── Fetchers (usable from Server Components and queryFn) ─────────────────────

export function fetchTodayGames(): Promise<TodayGame[]> {
  return apiGet<TodayGame[]>('/api/games/today')
}

export function fetchGameProjections(gameId: number): Promise<GameProjections> {
  return apiGet<GameProjections>(`/api/games/${gameId}/projections`)
}

export function fetchPlayer(playerId: number): Promise<PlayerDetail> {
  return apiGet<PlayerDetail>(`/api/players/${playerId}`)
}

export function fetchPlayerRecentStats(
  playerId: number,
  limit = 20,
): Promise<RecentStat[]> {
  const safeLimit = Math.min(Math.max(limit, 1), 100)
  return apiGet<RecentStat[]>(
    `/api/players/${playerId}/recent?limit=${safeLimit}`,
  )
}

export function fetchGameOdds(gameId: number): Promise<GameOdds> {
  return apiGet<GameOdds>(`/api/games/${gameId}/odds`)
}

export function fetchPitcherSkill(pitcherId: number): Promise<PitcherSkillSplit[]> {
  return apiGet<PitcherSkillSplit[]>(`/api/pitchers/${pitcherId}/skill`)
}

export function fetchBestPlays(date?: string, limit = 50): Promise<BestPlay[]> {
  const params = new URLSearchParams({ limit: String(limit) })
  if (date) params.set('date', date)
  return apiGet<BestPlay[]>(`/api/odds/best?${params}`)
}

export function fetchPitchTypes(): Promise<PitchTypeRef[]> {
  return apiGet<PitchTypeRef[]>('/api/leaderboards/pitch-types')
}

export function fetchAccuracy(days = 30): Promise<AccuracyResponse> {
  const safeDays = Math.min(Math.max(days, 7), 180)
  return apiGet<AccuracyResponse>(`/api/accuracy?days=${safeDays}`)
}

export function fetchPitchTypeLeaderboard(
  pitch: string,
  date?: string,
  limit = 20,
): Promise<PitchTypeLeaderboardEntry[]> {
  const params = new URLSearchParams({ pitch, limit: String(limit) })
  if (date) params.set('date', date)
  return apiGet<PitchTypeLeaderboardEntry[]>(`/api/leaderboards/pitch-type?${params}`)
}

// ── Home "Today's Board" helpers (additive, client-side aggregation) ──────────

/**
 * Flatten one game's batter projections into {@link FlatBatterPick} rows,
 * attaching game/opponent context so the home pick boards can rank across all
 * games. Each side's batters take the opposing side's team abbr as opponent.
 */
export function flattenGameBatters(
  game: TodayGame,
  projections: GameProjections,
): FlatBatterPick[] {
  const sides: Array<{ side: TeamBatters; oppAbbr: string }> = [
    { side: projections.home, oppAbbr: game.away.abbr },
    { side: projections.away, oppAbbr: game.home.abbr },
  ]
  return sides.flatMap(({ side, oppAbbr }) =>
    side.batters.map((batter) => ({
      batter,
      gameId: game.gameId,
      teamAbbr: side.teamAbbr,
      opponentAbbr: oppAbbr,
      opposingPitcherName: batter.opposingPitcher.name,
      opposingPitcherThrows: batter.opposingPitcher.throws,
      startTimeUtc: game.startTimeUtc,
      lineupConfirmed: batter.lineupConfirmed ?? side.lineupConfirmed,
    })),
  )
}

/** @deprecated Prefer named fetchers; kept for existing imports. */
export const api = {
  todayGames: fetchTodayGames,
  gameProjections: fetchGameProjections,
  recentStats: fetchPlayerRecentStats,
}

// ── TanStack Query keys ───────────────────────────────────────────────────────

export const queryKeys = {
  games: {
    all: ['games'] as const,
    today: () => [...queryKeys.games.all, 'today'] as const,
    projections: (gameId: number) =>
      ['game', 'projections', gameId] as const,
    odds: (gameId: number) => ['game', 'odds', gameId] as const,
  },
  odds: {
    best: (date?: string) => ['odds', 'best', date ?? 'today'] as const,
  },
  players: {
    detail: (playerId: number) => ['player', 'detail', playerId] as const,
    recent: (playerId: number, limit = 20) =>
      ['player', 'recent', playerId, limit] as const,
  },
  pitchers: {
    skill: (pitcherId: number) => ['pitcher', 'skill', pitcherId] as const,
  },
  leaderboards: {
    pitchTypes: () => ['leaderboards', 'pitch-types'] as const,
    pitchType: (pitch: string, date?: string, limit = 20) =>
      ['leaderboards', 'pitch-type', pitch, date ?? 'today', limit] as const,
  },
  accuracy: {
    trend: (days: number) => ['accuracy', 'trend', days] as const,
  },
}

// ── Query options (use with useQuery / prefetchQuery) ─────────────────────────

export function todayGamesQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.games.today(),
    queryFn: fetchTodayGames,
  })
}

export function gameProjectionsQueryOptions(gameId: number) {
  return queryOptions({
    queryKey: queryKeys.games.projections(gameId),
    queryFn: () => fetchGameProjections(gameId),
  })
}

export function gameOddsQueryOptions(gameId: number) {
  return queryOptions({
    queryKey: queryKeys.games.odds(gameId),
    queryFn: () => fetchGameOdds(gameId),
  })
}

export function pitcherSkillQueryOptions(pitcherId: number) {
  return queryOptions({
    queryKey: queryKeys.pitchers.skill(pitcherId),
    queryFn: () => fetchPitcherSkill(pitcherId),
    enabled: pitcherId > 0,
  })
}

export function bestPlaysQueryOptions(date?: string, limit = 50) {
  return queryOptions({
    queryKey: queryKeys.odds.best(date),
    queryFn: () => fetchBestPlays(date, limit),
  })
}

export function playerDetailQueryOptions(playerId: number) {
  return queryOptions({
    queryKey: queryKeys.players.detail(playerId),
    queryFn: () => fetchPlayer(playerId),
  })
}

export function playerRecentStatsQueryOptions(playerId: number, limit = 20) {
  return queryOptions({
    queryKey: queryKeys.players.recent(playerId, limit),
    queryFn: () => fetchPlayerRecentStats(playerId, limit),
  })
}

export function pitchTypesQueryOptions() {
  return queryOptions({
    queryKey: queryKeys.leaderboards.pitchTypes(),
    queryFn: fetchPitchTypes,
  })
}

export function accuracyQueryOptions(days = 30) {
  return queryOptions({
    queryKey: queryKeys.accuracy.trend(days),
    queryFn: () => fetchAccuracy(days),
  })
}

export function pitchTypeLeaderboardQueryOptions(
  pitch: string,
  date?: string,
  limit = 20,
) {
  return queryOptions({
    queryKey: queryKeys.leaderboards.pitchType(pitch, date, limit),
    queryFn: () => fetchPitchTypeLeaderboard(pitch, date, limit),
    enabled: Boolean(pitch),
  })
}
