import { AlertCircle } from 'lucide-react'
import { cn } from '@/lib/utils'

/**
 * Consistent error surface for a failed data query. Replaces the scattered bare
 * `text-rose-*` strings so every load failure reads the same and — when the caller
 * passes react-query's `refetch` — offers a one-click retry instead of a dead end.
 */
export function QueryError({
  message = 'Couldn’t load this. The API may be unreachable.',
  onRetry,
  className,
}: {
  message?: string
  onRetry?: () => void
  className?: string
}) {
  return (
    <div
      role="alert"
      className={cn(
        'flex flex-col items-start gap-2 rounded-xl border border-rose-400/30 bg-rose-400/[0.07] px-4 py-3 text-sm text-rose-300',
        className,
      )}
    >
      <div className="flex items-center gap-2">
        <AlertCircle className="h-4 w-4 shrink-0" aria-hidden="true" />
        <span>{message}</span>
      </div>
      {onRetry && (
        <button
          type="button"
          onClick={onRetry}
          className="rounded-md border border-rose-400/30 bg-rose-400/10 px-2.5 py-1 text-xs font-medium text-rose-200 transition-colors hover:bg-rose-400/20"
        >
          Try again
        </button>
      )}
    </div>
  )
}
