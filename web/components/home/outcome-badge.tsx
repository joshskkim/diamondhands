import { Check, X, Minus, Clock } from 'lucide-react'
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
