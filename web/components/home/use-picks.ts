'use client'

import { useQueries, useQuery } from '@tanstack/react-query'
import { fetchGameProjections, fetchTodayGames, flattenGameBatters } from '@/lib/api'
import type { FlatBatterPick, TodayGame } from '@/lib/types'

export interface PicksData {
  games: TodayGame[]
  /** Every projected batter across today's slate, with game/opponent context. */
  picks: FlatBatterPick[]
  /** Today's games are still loading. */
  isPending: boolean
  isError: boolean
  /** At least one game's batter projections are still loading. */
  projectionsLoading: boolean
  /** Refetch the slate (used by the error-state retry button). */
  refetch: () => void
}

/**
 * Aggregates today's slate client-side: fetches the games list, then fans out
 * one batter-projection request per game that already has a run projection, and
 * flattens all batters into a single ranked-ready array. Query keys mirror the
 * ones used by the game-detail and slate pages so the cache is shared.
 */
export function usePicks(): PicksData {
  const gamesQuery = useQuery({
    queryKey: ['games', 'today'],
    queryFn: fetchTodayGames,
  })
  const games = gamesQuery.data ?? []
  // Games without a run projection have no confirmed/projected lineup yet, so
  // their projections endpoint returns no batters — skip the request.
  const projGames = games.filter((g) => g.projection)

  const results = useQueries({
    queries: projGames.map((g) => ({
      queryKey: ['game', 'projections', g.gameId],
      queryFn: () => fetchGameProjections(g.gameId),
    })),
  })

  const picks = results.flatMap((r, i) =>
    r.data ? flattenGameBatters(projGames[i], r.data) : [],
  )

  return {
    games,
    picks,
    isPending: gamesQuery.isPending,
    isError: gamesQuery.isError,
    projectionsLoading: results.some((r) => r.isPending),
    refetch: () => gamesQuery.refetch(),
  }
}
