import { cn } from '@/lib/utils'

/** Tiny uppercase caption used throughout the app's boards and detail views. */
export const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

/** Pulsing placeholder block shown while a board's query is loading. */
export function Skeleton({ className = '' }: { className?: string }) {
  return <div className={cn('animate-pulse bg-white/5 rounded', className)} />
}
