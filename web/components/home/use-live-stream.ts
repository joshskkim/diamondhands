'use client'

import { useEffect } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { API_BASE, queryKeys } from '@/lib/api'
import type { LiveGame, TodayGame } from '@/lib/types'

const DEAD_STATUSES = new Set(['Postponed', 'Suspended', 'Cancelled'])

/** Whether any game on the slate is plausibly in progress — i.e. worth holding an SSE
 *  connection open for. True once first pitch has passed and the game isn't final/dead.
 *  Falls back to the start time because games.status only refreshes on the ~30-min cron,
 *  so a freshly-started game may still read 'Scheduled' for a bit. */
export function hasLiveGames(games: TodayGame[] | undefined): boolean {
  if (!games) return false
  const now = Date.now()
  return games.some((g) => {
    if (g.detailedStatus && DEAD_STATUSES.has(g.detailedStatus)) return false
    if (g.finalHomeScore != null && g.finalAwayScore != null) return false
    if (g.status === 'Final') return false
    if (g.status === 'Live') return true
    const start = new Date(g.startTimeUtc).getTime()
    return Number.isFinite(start) && start <= now
  })
}

/**
 * Subscribes to the live game-state SSE stream while the slate has in-progress games and
 * patches the streamed deltas into the existing `todayGames` query cache — so every board
 * that reads `todayGames` re-renders live with no board-specific data source. The 5-minute
 * `todayGames` poll remains as a cold-start / safety net.
 */
export function useLiveStream(games: TodayGame[] | undefined): void {
  const queryClient = useQueryClient()
  const active = hasLiveGames(games)

  useEffect(() => {
    if (!active) return

    const source = new EventSource(`${API_BASE}/api/games/live/stream`, {
      withCredentials: true,
    })

    source.addEventListener('games', (ev) => {
      let deltas: LiveGame[]
      try {
        deltas = JSON.parse((ev as MessageEvent).data)
      } catch {
        return
      }
      const byId = new Map(deltas.map((d) => [d.gameId, d]))
      queryClient.setQueryData<TodayGame[]>(queryKeys.games.today(), (prev) =>
        prev?.map((g) => {
          const d = byId.get(g.gameId)
          return d
            ? {
                ...g,
                status: d.status,
                liveHomeScore: d.liveHomeScore,
                liveAwayScore: d.liveAwayScore,
                liveCurrentInning: d.liveCurrentInning,
                liveInningState: d.liveInningState,
                liveIsTop: d.liveIsTop,
                // First-inning runs share the home_score_1st/away_score_1st columns that
                // /api/games/today maps into finalHome/AwayFirstInningRuns — patch them so
                // the NRFI/YRFI badge resolves at end of the 1st, not the 5-min poll. Keep
                // any value we already have if the stream hasn't populated it yet.
                finalHomeFirstInningRuns:
                  d.liveHomeFirstInningRuns ?? g.finalHomeFirstInningRuns,
                finalAwayFirstInningRuns:
                  d.liveAwayFirstInningRuns ?? g.finalAwayFirstInningRuns,
              }
            : g
        }),
      )
    })

    return () => source.close()
  }, [active, queryClient])
}
