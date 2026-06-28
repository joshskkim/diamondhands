import { Check, X, Minus, Clock, Radio } from 'lucide-react'
import { cn } from '@/lib/utils'
import type { PickOutcome } from '@/lib/picks'

const META: Record<
  PickOutcome,
  { label: string; Icon: typeof Check; cls: string }
> = {
  won: { label: 'Hit', Icon: Check, cls: 'text-emerald-300 border-emerald-400/40 bg-emerald-500/10' },
  lost: { label: 'Miss', Icon: X, cls: 'text-rose-300 border-rose-400/40 bg-rose-500/10' },
  push: { label: 'Push', Icon: Minus, cls: 'text-zinc-300 border-white/15 bg-white/5' },
  pending: { label: 'Pending', Icon: Clock, cls: 'text-zinc-500 border-white/10 bg-white/5' },
  // In-progress — never green/red until the pick is actually settled.
  live: { label: 'Live', Icon: Radio, cls: 'text-cyan-300 border-cyan-400/40 bg-cyan-500/10 animate-pulse' },
}

/**
 * A ✓/✗/push/pending chip for a graded pick. `iconOnly` renders a compact badge
 * (for game cards / tight rows); otherwise it shows the label too.
 */
export function OutcomeBadge({
  outcome,
  iconOnly = false,
  className,
}: {
  outcome: PickOutcome
  iconOnly?: boolean
  className?: string
}) {
  const { label, Icon, cls } = META[outcome]
  return (
    <span
      title={label}
      aria-label={label}
      className={cn(
        'inline-flex shrink-0 items-center gap-1 rounded border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide',
        cls,
        className,
      )}
    >
      <Icon className="h-3 w-3" aria-hidden="true" />
      {!iconOnly && label}
    </span>
  )
}

/**
 * A thin live progress bar for an in-progress over/under-style pick: shows the running
 * count vs the line and fills toward it. `onPace`, when given, draws a caret at the
 * projected-final position so you can see whether it's tracking over or under.
 */
type LiveTone = 'live' | 'won' | 'lost'

const TONE_TEXT: Record<LiveTone, string> = {
  live: 'text-cyan-300',
  won: 'text-emerald-300',
  lost: 'text-rose-300',
}
const TONE_BAR: Record<LiveTone, string> = {
  live: 'bg-cyan-500',
  won: 'bg-emerald-500',
  lost: 'bg-rose-500',
}

export function LiveProgress({
  actual,
  line,
  onPace,
  tone = 'live',
  className,
}: {
  actual: number
  line: number
  onPace?: number | null
  tone?: LiveTone
  className?: string
}) {
  const denom = line > 0 ? line : 1
  const pct = Math.min(100, Math.max(0, (actual / denom) * 100))
  const pacePct =
    onPace != null ? Math.min(100, Math.max(0, (onPace / denom) * 100)) : null
  return (
    <div className={cn('flex items-center gap-1.5', className)}>
      <span className={cn('font-mono tabular-nums text-[11px]', TONE_TEXT[tone])}>
        {actual}
        <span className="text-zinc-600">/{line}</span>
      </span>
      <div className="relative h-1 w-12 rounded bg-black/40 overflow-hidden">
        <div className={cn('absolute inset-y-0 left-0', TONE_BAR[tone])} style={{ width: `${pct}%` }} />
        {pacePct != null && (
          <div
            className="absolute inset-y-0 w-px bg-amber-300"
            style={{ left: `${pacePct}%` }}
            title="On-pace projection"
          />
        )}
      </div>
    </div>
  )
}
