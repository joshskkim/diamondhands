import type { TodayGame } from '@/lib/types'
import { cn } from '@/lib/utils'
import { liveRunLineMargin, liveTotalPace } from '@/lib/picks'
import { LiveProgress } from './outcome-badge'

const ORDINALS = ['', '1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th']
export function inningLabel(inning: number): string {
  return ORDINALS[inning] ?? `${inning}th`
}

const DEAD_STATUSES = new Set(['Postponed', 'Suspended', 'Cancelled'])

/** Is this game in progress (and so worth a live tracker)? */
export function gameIsLive(game: TodayGame | undefined): boolean {
  if (!game) return false
  if (game.detailedStatus && DEAD_STATUSES.has(game.detailedStatus)) return false
  if (game.finalHomeScore != null && game.finalAwayScore != null) return false
  const hasLive = game.liveHomeScore != null && game.liveAwayScore != null
  return game.status === 'Live' || hasLive
}

/** The live score + inning line, e.g. "PHI 2–6 NYM  ▼ 9th". */
function ScoreLine({ game }: { game: TodayGame }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="font-mono tabular-nums text-zinc-100">
        {game.away.abbr} {game.liveAwayScore}–{game.liveHomeScore} {game.home.abbr}
      </span>
      {game.liveCurrentInning != null && (
        <span className="inline-flex items-center gap-0.5 text-[11px] font-semibold rounded px-1.5 py-0.5 text-cyan-300 border border-cyan-400/40 bg-cyan-500/10">
          {game.liveIsTop ? '▲' : '▼'} {inningLabel(game.liveCurrentInning)}
        </span>
      )}
    </span>
  )
}

/**
 * The live in-game tracker shown on a pick card while its game is being played: the
 * running score + inning, plus a market-specific read of where the pick stands —
 * a total-vs-line progress bar, or a covering/leading indicator. Renders nothing when
 * the game isn't live.
 */
export function LivePickTracker({
  game,
  market,
  side,
  line,
  className,
}: {
  game: TodayGame | undefined
  market: string
  side: string
  line: number | null
  className?: string
}) {
  if (!gameIsLive(game)) return null
  const g = game!
  const liveHome = g.liveHomeScore
  const liveAway = g.liveAwayScore
  const liveTotal = liveHome != null && liveAway != null ? liveHome + liveAway : null

  let detail: React.ReactNode = null
  if (market === 'total' && liveTotal != null && line != null) {
    detail = (
      <LiveProgress actual={liveTotal} line={line} onPace={liveTotalPace(liveTotal, g.liveCurrentInning, g.liveIsTop)} />
    )
  } else if (market === 'run_line' && line != null) {
    const margin = liveRunLineMargin(side === 'home', liveHome, liveAway)
    if (margin != null) {
      const covering = margin + line > 0
      detail = (
        <span className={cn('text-[11px] font-medium', covering ? 'text-emerald-300' : 'text-rose-300')}>
          {margin > 0 ? `+${margin}` : margin} · {covering ? 'covering' : 'not covering'}
        </span>
      )
    }
  } else if (market === 'moneyline' && liveHome != null && liveAway != null) {
    const myRuns = side === 'home' ? liveHome : liveAway
    const oppRuns = side === 'home' ? liveAway : liveHome
    const word = myRuns > oppRuns ? 'leading' : myRuns < oppRuns ? 'trailing' : 'tied'
    detail = (
      <span className={cn('text-[11px] font-medium', word === 'leading' ? 'text-emerald-300' : word === 'trailing' ? 'text-rose-300' : 'text-zinc-400')}>
        {word}
      </span>
    )
  }

  return (
    <div className={cn('flex items-center justify-between gap-2 rounded border border-cyan-400/20 bg-cyan-500/[0.04] px-2.5 py-1.5', className)}>
      <ScoreLine game={g} />
      {detail}
    </div>
  )
}
