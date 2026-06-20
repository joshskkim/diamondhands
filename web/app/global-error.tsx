'use client'

// App Router global error boundary — catches render errors in the root layout/segments and
// reports them to Sentry (no-op when Sentry isn't initialized). Must render its own <html>.
import * as Sentry from '@sentry/nextjs'
import { useEffect } from 'react'

export default function GlobalError({
  error,
  reset,
}: {
  error: Error & { digest?: string }
  reset: () => void
}) {
  useEffect(() => {
    Sentry.captureException(error)
  }, [error])

  return (
    <html lang="en">
      <body className="flex min-h-screen items-center justify-center bg-[#0b0d12] text-zinc-200">
        <div className="text-center">
          <h1 className="text-2xl font-bold">Something went wrong</h1>
          <p className="mt-2 text-sm text-zinc-500">
            An unexpected error occurred. It&apos;s been reported.
          </p>
          <button
            onClick={() => reset()}
            className="mt-6 rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-[#06222b] transition-colors hover:bg-cyan-400"
          >
            Try again
          </button>
        </div>
      </body>
    </html>
  )
}
