import type { TodayGame } from '@/lib/types'
import { cn } from '@/lib/utils'
import { liveRunLineMargin, liveTotalPace, type PickOutcome } from '@/lib/picks'
import { LiveProgress } from './outcome-badge'

const ORDINALS = ['', '1st', '2nd', '3rd', '4th', '5th', '6th', '7th', '8th', '9th']
export function inningLabel(inning: number): string {
  return ORDINALS[inning] ?? `${inning}th`
}

const DEAD_STATUSES = new Set(['Postponed', 'Suspended', 'Cancelled'])

// How long after the last live_* write we keep trusting a game as "live". Once the live
// feed stops (game ran past the live-refresh window, or a cron gap) the polled state ages
// past this and the tracker drops — so a finished game never stays stuck reading "Live"
// until the next finalizer. Comfortably above the ~30s live cadence + 5-min todayGames poll.
const STALE_MS = 20 * 60 * 1000

/** Is this game in progress (and so worth a live tracker)? */
export function gameIsLive(game: TodayGame | undefined): boolean {
  if (!game) return false
  if (game.detailedStatus && DEAD_STATUSES.has(game.detailedStatus)) return false
  if (game.status === 'Final') return false
  if (game.finalHomeScore != null && game.finalAwayScore != null) return false
  // Stale live state means the feed stopped — don't keep showing it as live.
  if (game.liveUpdatedAt != null) {
    const age = Date.now() - new Date(game.liveUpdatedAt).getTime()
    if (Number.isFinite(age) && age > STALE_MS) return false
  }
  const hasLive = game.liveHomeScore != null && game.liveAwayScore != null
  return game.status === 'Live' || hasLive
}

/** The small "▼ 9th" inning chip, shared by the game-score line and the prop tracker. */
function InningChip({ game }: { game: TodayGame }) {
  if (game.liveCurrentInning == null) return null
  return (
    <span className="inline-flex items-center gap-0.5 text-[11px] font-semibold rounded px-1.5 py-0.5 text-cyan-300 border border-cyan-400/40 bg-cyan-500/10">
      {game.liveIsTop ? '▲' : '▼'} {inningLabel(game.liveCurrentInning)}
    </span>
  )
}

/** The live score + inning line, e.g. "PHI 2–6 NYM  ▼ 9th". */
function ScoreLine({ game }: { game: TodayGame }) {
  return (
    <span className="inline-flex items-center gap-2">
      <span className="font-mono tabular-nums text-zinc-100">
        {game.away.abbr} {game.liveAwayScore}–{game.liveHomeScore} {game.home.abbr}
      </span>
      <InningChip game={game} />
    </span>
  )
}

/**
 * The live in-game tracker shown on a pick card while its game is being played: the
 * running score + inning, plus a market-specific read of where the pick stands —
 * a total-vs-line progress bar, or a covering/leading indicator. Renders nothing when
 * the game isn't live.
 */
// Box border/background by settlement state — turns green/red the moment the pick locks,
// otherwise the neutral cyan "live" look while it's still in play.
const BOX_TONE: Record<'live' | 'won' | 'lost', string> = {
  live: 'border-cyan-400/20 bg-cyan-500/[0.04]',
  won: 'border-emerald-400/40 bg-emerald-500/[0.08]',
  lost: 'border-rose-400/40 bg-rose-500/[0.08]',
}

export function LivePickTracker({
  game,
  market,
  side,
  line,
  outcome,
  count,
  className,
}: {
  game: TodayGame | undefined
  market: string
  side: string
  line: number | null
  outcome?: PickOutcome
  /** Live count for a player prop (K/outs/ER/H, hits/HR) — shows a count-vs-line bar. */
  count?: number | null
  className?: string
}) {
  if (!gameIsLive(game)) return null
  const g = game!
  const liveHome = g.liveHomeScore
  const liveAway = g.liveAwayScore
  const liveTotal = liveHome != null && liveAway != null ? liveHome + liveAway : null

  // Once the pick is locked (won/lost) the whole tracker takes that color; otherwise live.
  const tone = outcome === 'won' ? 'won' : outcome === 'lost' ? 'lost' : 'live'

  let detail: React.ReactNode = null
  if (market === 'total' && liveTotal != null && line != null) {
    detail = (
      <LiveProgress
        actual={liveTotal}
        line={line}
        onPace={liveTotalPace(liveTotal, g.liveCurrentInning, g.liveIsTop)}
        tone={tone}
      />
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
  } else if (count != null && line != null) {
    // Player prop (pitcher K/outs/ER/H, batter hits/HR): live count vs the line.
    detail = <LiveProgress actual={count} line={line} tone={tone} />
  }

  return (
    <div className={cn('flex items-center justify-between gap-2 rounded border px-2.5 py-1.5', BOX_TONE[tone], className)}>
      <ScoreLine game={g} />
      {detail}
    </div>
  )
}

// The word for a cleared ≥1 batter prop, keyed by the stat's unit.
const CLEARED_LABEL: Record<string, string> = { H: 'hit', HR: 'HR', K: 'K', BB: 'walk' }

/** The settle word for a player prop while it's live: ✓ cleared, ✗ busted, or "in play". */
function PropStatus({ outcome, clearedLabel }: { outcome?: PickOutcome; clearedLabel: string }) {
  if (outcome === 'won') {
    return <span className="text-[11px] font-semibold text-emerald-300">✓ {clearedLabel}</span>
  }
  if (outcome === 'lost') {
    return <span className="text-[11px] font-semibold text-rose-300">✗</span>
  }
  return <span className="text-[11px] font-medium text-zinc-500">in play</span>
}

/**
 * The live in-game tracker for a PLAYER-PROP card — tracks the prop itself, not the game
 * score. For a batter it shows his running box line and whether he's cleared the prop
 * ("1-for-3 · 1 H ✓ hit"); for a pitcher his count toward the line over the innings he's
 * thrown ("4 K · 5.0 IP" + a count-vs-line bar). The inning chip is kept as small context
 * so you know how much game is left. Renders nothing when the game isn't live.
 */
export function LivePropTracker({
  game,
  line,
  outcome,
  count,
  unit,
  batterLine,
  outs,
  className,
}: {
  game: TodayGame | undefined
  line: number | null
  outcome?: PickOutcome
  /** The prop's live stat count (hits/HR/K/BB for a batter; K/outs/H/ER for a pitcher). */
  count?: number | null
  /** Display unit: 'H' | 'HR' | 'K' | 'BB' (batter) or 'K' | 'outs' | 'H' | 'ER' (pitcher). */
  unit: string
  /** Batter cards: the running for-line context. Omit for pitcher cards. */
  batterLine?: { hits: number | null; atBats: number | null } | null
  /** Pitcher cards: outs recorded, rendered as innings pitched. Omit for batter cards. */
  outs?: number | null
  className?: string
}) {
  if (!gameIsLive(game)) return null
  const g = game!
  const tone = outcome === 'won' ? 'won' : outcome === 'lost' ? 'lost' : 'live'

  let body: React.ReactNode
  if (batterLine) {
    const forLine =
      batterLine.atBats != null ? `${batterLine.hits ?? 0}-for-${batterLine.atBats}` : '—'
    body = (
      <span className="inline-flex items-center gap-2">
        <span className="font-mono tabular-nums text-zinc-100">{forLine}</span>
        {count != null && (
          <span className="font-mono tabular-nums text-zinc-400">
            · {count} {unit}
          </span>
        )}
        <PropStatus outcome={outcome} clearedLabel={CLEARED_LABEL[unit] ?? unit} />
      </span>
    )
  } else {
    const ip = outs != null ? `${Math.floor(outs / 3)}.${outs % 3}` : null
    body = (
      <span className="inline-flex items-center gap-2">
        <span className="font-mono tabular-nums text-zinc-100">
          {count ?? 0} {unit}
          {ip != null && <span className="text-zinc-500"> · {ip} IP</span>}
        </span>
        {count != null && line != null && <LiveProgress actual={count} line={line} tone={tone} />}
      </span>
    )
  }

  return (
    <div className={cn('flex items-center justify-between gap-2 rounded border px-2.5 py-1.5', BOX_TONE[tone], className)}>
      {body}
      <InningChip game={g} />
    </div>
  )
}
