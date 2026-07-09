import { cn } from '@/lib/utils'
import { microLabel } from '@/components/ui/primitives'

const chipBase =
  'inline-flex items-center gap-1 text-[11px] rounded px-1.5 py-0.5 border'

/** Label-over-value stat tile (Model / Fair / Edge / EV, …). Shared so cards don't
 *  paste the microLabel + mono-value pair inline. */
export function Stat({
  label,
  value,
  className,
}: {
  label: string
  value: string
  className?: string
}) {
  return (
    <div>
      <div className={microLabel}>{label}</div>
      <div className={cn('text-[13px] font-mono tabular-nums', className)}>{value}</div>
    </div>
  )
}

export function Chip({
  tone = 'neutral',
  className,
  children,
}: {
  tone?: 'neutral' | 'confirmed' | 'projected' | 'info'
  className?: string
  children: React.ReactNode
}) {
  const tones = {
    neutral: 'bg-white/5 border-white/10 text-zinc-300',
    confirmed: 'text-emerald-300 border-emerald-400/30 bg-emerald-400/10',
    projected: 'text-amber-300 border-amber-400/30 bg-amber-400/10',
    info: 'text-cyan-300 border-cyan-400/30 bg-cyan-400/10',
  }
  return <span className={cn(chipBase, tones[tone], className)}>{children}</span>
}

/** Human-readable pitch-type names, shared by batter & pitcher views. */
export const PITCH_NAMES: Record<string, string> = {
  FF: '4-Seam',
  SI: 'Sinker',
  FC: 'Cutter',
  SL: 'Slider',
  CU: 'Curve',
  CH: 'Change',
  FS: 'Splitter',
}
