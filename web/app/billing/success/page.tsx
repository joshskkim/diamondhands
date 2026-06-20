'use client'

import { useEffect } from 'react'
import Link from 'next/link'
import { useQueryClient } from '@tanstack/react-query'

export default function BillingSuccessPage() {
  const qc = useQueryClient()

  // The webhook flips us to Pro; refetch the current user so the badge appears.
  // Retry briefly in case the webhook lands a moment after the redirect.
  useEffect(() => {
    void qc.invalidateQueries({ queryKey: ['auth', 'me'] })
    const t = setTimeout(() => void qc.invalidateQueries({ queryKey: ['auth', 'me'] }), 2500)
    return () => clearTimeout(t)
  }, [qc])

  return (
    <div className="max-w-6xl mx-auto w-full px-4 py-8">
      <div className="mx-auto max-w-md text-center">
        <div className="bg-[#0e1015] border border-white/10 rounded-xl p-8">
          <h1 className="text-2xl font-bold tracking-tight text-zinc-100">You&apos;re Pro 🎉</h1>
          <p className="text-zinc-500 text-sm mt-3">
            Thanks for subscribing to Diamond Pro. Your account is being updated.
          </p>
          <Link
            href="/profile"
            className="mt-6 inline-block rounded-lg bg-cyan-500 px-4 py-2 text-sm font-semibold text-[#06222b] transition-colors hover:bg-cyan-400"
          >
            Go to your profile
          </Link>
        </div>
      </div>
    </div>
  )
}
