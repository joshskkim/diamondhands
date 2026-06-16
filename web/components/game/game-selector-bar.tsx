'use client'

import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ChevronDown } from 'lucide-react'
import Link from 'next/link'
import { useEffect, useRef, useState, type CSSProperties } from 'react'
import { todayGamesQueryOptions } from '@/lib/api'
import { cn, parseApiDate } from '@/lib/utils'

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
  const [open, setOpen] = useState(false)

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
      if (el.scrollWidth <= el.clientWidth) return // nothing to scroll
      if (Math.abs(e.deltaY) <= Math.abs(e.deltaX)) return // let native horizontal pass
      el.scrollLeft += e.deltaY
      e.preventDefault()
    }
    el.addEventListener('wheel', onWheel, { passive: false })
    return () => el.removeEventListener('wheel', onWheel)
  }, [games])

  if (!games || games.length === 0) return null

  const active = games.find((g) => g.gameId === activeGameId)
  const activeGlow = active
    ? favoriteGlow(active.projection?.expectedHomeRuns, active.projection?.expectedAwayRuns)
    : favoriteGlow(null, null)

  return (
    <div className="sticky top-12 md:top-0 z-30 -mx-4 mb-6 border-b border-white/10 bg-[#08090d]/90 px-4 py-2 backdrop-blur">
      {/* desktop: horizontal chip strip */}
      <div ref={stripRef} className="scrollbar-slim hidden gap-2 overflow-x-auto md:flex">
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
              <MatchupMeta startTimeUtc={g.startTimeUtc} total={g.projection?.expectedTotal} />
            </Link>
          )
        })}
      </div>

      {/* mobile: dropdown switcher */}
      <div className="relative md:hidden">
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          aria-expanded={open}
          className="flex w-full items-center justify-between gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-left"
        >
          <div className="min-w-0">
            {active ? (
              <>
                <MatchupLabel away={active.away.abbr} home={active.home.abbr} glow={activeGlow} />
                <MatchupMeta startTimeUtc={active.startTimeUtc} total={active.projection?.expectedTotal} />
              </>
            ) : (
              <span className="text-sm font-medium text-zinc-300">
                Today&apos;s games ({games.length})
              </span>
            )}
          </div>
          <ChevronDown
            className={cn('h-4 w-4 shrink-0 text-zinc-400 transition-transform', open && 'rotate-180')}
          />
        </button>

        {open && (
          <div className="absolute inset-x-0 top-full z-40 mt-1 max-h-[60vh] overflow-y-auto rounded-lg border border-white/10 bg-[#0e1015] py-1 shadow-xl">
            {games.map((g) => {
              const isActive = g.gameId === activeGameId
              const glow = favoriteGlow(g.projection?.expectedHomeRuns, g.projection?.expectedAwayRuns)
              return (
                <Link
                  key={g.gameId}
                  href={`/mlb/games/${g.gameId}`}
                  onClick={() => setOpen(false)}
                  className={cn(
                    'flex items-center justify-between gap-3 px-3 py-2 transition-colors',
                    isActive ? 'bg-cyan-400/10 text-cyan-300' : 'text-zinc-300 hover:bg-white/5',
                  )}
                >
                  <MatchupLabel away={g.away.abbr} home={g.home.abbr} glow={glow} />
                  <MatchupMeta startTimeUtc={g.startTimeUtc} total={g.projection?.expectedTotal} />
                </Link>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
