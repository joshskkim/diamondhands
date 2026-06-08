import { cn } from '@/lib/utils'

/**
 * The Diamond brand mark: a real diamond (rotated-square via clip-path) filled
 * with a cyan→blue gradient and a soft glow. Shared by the sidebar brand and the
 * mobile top bar so the logo stays in one place.
 */
export function DiamondMark({ className }: { className?: string }) {
  return (
    <span
      aria-hidden
      className={cn(
        'inline-block h-3 w-3 shrink-0 bg-gradient-to-br from-cyan-400 to-blue-500 drop-shadow-[0_0_6px_rgba(34,211,238,0.7)]',
        className,
      )}
      style={{ clipPath: 'polygon(50% 0%, 100% 50%, 50% 100%, 0% 50%)' }}
    />
  )
}
