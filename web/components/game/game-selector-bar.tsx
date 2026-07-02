'use client'

import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import Link from 'next/link'
import { useEffect, useRef, type CSSProperties } from 'react'
import { todayGamesQueryOptions } from '@/lib/api'
import type { TodayGame } from '@/lib/types'
import { cn, parseApiDate } from '@/lib/utils'

const DEAD_STATUSES = new Set(['Postponed', 'Suspended', 'Cancelled'])

/**
 * Projected-favorite glow. From the game's expected runs, picks the favorite side
 * and an intensity 0..1 that scales with the run margin (capped at ~2 R = a big
 * favorite). The favorite's abbreviation gets a colored glow whose brightness/spread
 * tracks how strongly we favor them; pick'ems stay neutral.
 */
const _GLOW_CAP_RUNS = 2.0

function favoriteGlow(
  home: number | null | undefined,
  away: number | null | undefined,
): { side: 'home' | 'away' | null; style: CSSProperties } {
  if (home == null || away == null) return { side: null, style: {} }
  const margin = Math.abs(home - away)
  if (margin < 0.05) return { side: null, style: {} } // effective pick'em
  const t = Math.min(margin / _GLOW_CAP_RUNS, 1) // 0..1 intensity
  const side = home > away ? 'home' : 'away'
  const style: CSSProperties = {
    color: `rgba(110, 231, 183, ${0.7 + 0.3 * t})`, // emerald, brighter when more favored
    textShadow: `0 0 ${5 + 11 * t}px rgba(52, 211, 153, ${0.35 + 0.5 * t})`,
  }
  return { side, style }
}

// A single matchup label: AWY @ HOM, with the projected favorite glowing.
function MatchupLabel({
  away,
  home,
  glow,
}: {
  away: string
  home: string
  glow: ReturnType<typeof favoriteGlow>
}) {
  return (
    <div className="flex items-center gap-2 text-sm font-semibold tracking-tight whitespace-nowrap">
      <span style={glow.side === 'away' ? glow.style : undefined}>{away}</span>
      <span className="font-normal text-zinc-600">@</span>
      <span style={glow.side === 'home' ? glow.style : undefined}>{home}</span>
    </div>
  )
}

// Time · total line shown beneath a matchup.
function MatchupMeta({
  startTimeUtc,
  total,
}: {
  startTimeUtc: string
  total: number | null | undefined
}) {
  return (
    <div className="mt-0.5 flex items-center gap-1.5 text-[10px] text-zinc-500 whitespace-nowrap">
      <span className="font-mono tabular-nums">{format(parseApiDate(startTimeUtc), 'h:mm a')}</span>
      {total != null && (
        <>
          <span className="text-zinc-700">·</span>
          <span className="font-mono tabular-nums">{total.toFixed(1)} R</span>
        </>
      )}
    </div>
  )
}

// The running/final score with a short game-state suffix, once a game is live or final.
interface ScoreState {
  away: number
  home: number
  leadSide: 'home' | 'away' | null
  label: string
}

// Short inning tag, e.g. "Top 5" / "Bot 3" / "Mid 4".
function inningLabel(state: string | null, inning: number | null): string {
  const prefix =
    state === 'Top'
      ? 'Top'
      : state === 'Bottom'
        ? 'Bot'
        : state === 'Middle'
          ? 'Mid'
          : state === 'End'
            ? 'End'
            : (state ?? 'Live')
  return `${prefix} ${inning ?? ''}`.trim()
}

// Live/final score for a game, or null while it's still scheduled (or lacks a score).
function scoreState(g: TodayGame): ScoreState | null {
  const isFinal = g.finalHomeScore != null && g.finalAwayScore != null
  const home = isFinal ? g.finalHomeScore : g.liveHomeScore
  const away = isFinal ? g.finalAwayScore : g.liveAwayScore
  const isLive = !isFinal && (g.status === 'Live' || (home != null && away != null))
  if ((!isFinal && !isLive) || home == null || away == null) return null
  const leadSide = home > away ? 'home' : away > home ? 'away' : null
  const label = isFinal ? 'Final' : inningLabel(g.liveInningState, g.liveCurrentInning)
  return { away, home, leadSide, label }
}

// Emerald when the leading side is the team we projected to win, rose when it's the other
// team, neutral on a tie — so the color reads "our pick is / isn't ahead" at a glance.
function scoreColor(
  side: 'home' | 'away',
  leadSide: 'home' | 'away' | null,
  favSide: 'home' | 'away' | null,
): string {
  if (side !== leadSide || favSide == null) return 'text-zinc-300' // trailing/tied or no lean
  return leadSide === favSide ? 'text-emerald-400' : 'text-rose-400'
}

// AWY score @ HOM score · state, with the leading team's number colored by our prediction.
function MatchupScore({ score, favSide }: { score: ScoreState; favSide: 'home' | 'away' | null }) {
  const { away, home, leadSide, label } = score
  return (
    <div className="mt-0.5 flex items-center gap-1.5 text-[10px] whitespace-nowrap">
      <span className={cn('font-mono font-semibold tabular-nums', scoreColor('away', leadSide, favSide))}>
        {away}
      </span>
      <span className="text-zinc-600">@</span>
      <span className={cn('font-mono font-semibold tabular-nums', scoreColor('home', leadSide, favSide))}>
        {home}
      </span>
      <span className="text-zinc-700">·</span>
      <span className="font-mono tabular-nums text-zinc-500">{label}</span>
    </div>
  )
}

// The sub-line beneath a matchup: dead-game status, else the live/final score, else time · total.
function ChipMeta({ game, favSide }: { game: TodayGame; favSide: 'home' | 'away' | null }) {
  if (game.detailedStatus && DEAD_STATUSES.has(game.detailedStatus)) {
    return (
      <div className="mt-0.5 text-[10px] font-medium text-zinc-500 whitespace-nowrap">
        {game.detailedStatus}
      </div>
    )
  }
  const score = scoreState(game)
  if (score) return <MatchupScore score={score} favSide={favSide} />
  return <MatchupMeta startTimeUtc={game.startTimeUtc} total={game.projection?.expectedTotal} />
}

/**
 * Sticky game switcher for today's slate. On desktop it's a horizontally
 * scrolling strip of chips; on mobile it collapses to a dropdown (the strip
 * fights the page's vertical flow on a narrow screen). Both read the already
 * cached slate, so switching is an instant client navigation, and the projected
 * favorite glows more vividly the more we favor them.
 */
export function GameSelectorBar({ activeGameId }: { activeGameId?: number }) {
  const { data: games } = useQuery(todayGamesQueryOptions())
  const activeRef = useRef<HTMLAnchorElement | null>(null)
  const stripRef = useRef<HTMLDivElement | null>(null)

  // Bring the current game into view when the bar mounts / the slate loads.
  useEffect(() => {
    activeRef.current?.scrollIntoView({ inline: 'center', block: 'nearest' })
  }, [games, activeGameId])

  // Translate vertical mouse-wheel into horizontal scroll. The strip hides its
  // scrollbar (scrollbar-slim) and scrolls fine via trackpad/drag, but a plain
  // vertical wheel does nothing on a horizontal-only container, so mouse users
  // are stuck. React's synthetic onWheel is passive (preventDefault is a no-op),
  // so attach a native non-passive listener. Native horizontal gestures (deltaX,
  // e.g. trackpad swipe) are left untouched.
  useEffect(() => {
    const el = stripRef.current
    if (!el) return
    const onWheel = (e: WheelEvent) => {
      if (el.scrollWidth <= el.clientWidth) return // nothing to scroll horizontally
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return // horizontal gesture → native
      // Normalize wheel units to pixels. Some browsers/mice report lines (deltaMode 1,
      // deltaY ~1-3) or pages (2); applying deltaY raw then barely moves the strip.
      const step =
        e.deltaMode === 1
          ? e.deltaY * 16
          : e.deltaMode === 2
            ? e.deltaY * el.clientWidth
            : e.deltaY
      el.scrollLeft += step
      e.preventDefault()
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [games])

  if (!games || games.length === 0) return null

  return (
    <div className="sticky top-12 md:top-0 z-30 -mx-4 mb-6 border-b border-white/10 bg-[#08090d]/90 px-4 py-2 backdrop-blur">
      {/* horizontal chip strip — scrolls with the wheel on desktop, touch-drag on mobile */}
      <div ref={stripRef} className="scrollbar-slim flex gap-2 overflow-x-auto">
        {games.map((g) => {
          const isActive = g.gameId === activeGameId
          const glow = favoriteGlow(g.projection?.expectedHomeRuns, g.projection?.expectedAwayRuns)
          return (
            <Link
              key={g.gameId}
              ref={isActive ? activeRef : undefined}
              href={`/mlb/games/${g.gameId}`}
              className={cn(
                'shrink-0 rounded-lg border px-3 py-1.5 transition-colors',
                isActive
                  ? 'border-cyan-400/30 bg-cyan-400/10 text-cyan-300'
                  : 'border-white/10 bg-white/5 text-zinc-300 hover:bg-white/10 hover:text-zinc-100',
              )}
            >
              <MatchupLabel away={g.away.abbr} home={g.home.abbr} glow={glow} />
              <ChipMeta game={g} favSide={glow.side} />
            </Link>
          )
        })}
      </div>
    </div>
  )
}
