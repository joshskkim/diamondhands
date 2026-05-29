import { queryOptions } from '@tanstack/react-query'
import type { GameProjections, PlayerDetail, RecentStat, TodayGame } from './types'

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
  const res = await fetch(`${API_BASE}${path}`)
  if (!res.ok) throw new ApiError(res.status, path)
  return res.json() as Promise<T>
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
  },
  players: {
    detail: (playerId: number) => ['player', 'detail', playerId] as const,
    recent: (playerId: number, limit = 20) =>
      ['player', 'recent', playerId, limit] as const,
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
