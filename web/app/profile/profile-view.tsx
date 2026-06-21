'use client'

import { useState } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/components/auth-provider'
import { createCheckout, createPortal, ApiError } from '@/lib/api'

type Interval = 'monthly' | 'annual'

function messageFor(err: unknown): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return 'Please sign in again.'
    if (err.status === 503) return 'Billing is not available right now.'
    if (err.status === 400) return 'No billing account yet — subscribe first.'
  }
  return 'Something went wrong. Please try again.'
}

export function ProfileView() {
  const router = useRouter()
  const { user, isLoading } = useAuth()
  const [busy, setBusy] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  if (isLoading) {
    return <p className="text-sm text-zinc-500">Loading…</p>
  }

  if (!user) {
    return (
      <div className="text-center">
        <p className="text-zinc-400 text-sm">
          You&apos;re not signed in.{' '}
          <button
            onClick={() => router.push('/signin')}
            className="font-medium text-cyan-400 hover:text-cyan-300"
          >
            Sign in
          </button>{' '}
          to manage your subscription.
        </p>
      </div>
    )
  }

  async function go(action: 'checkout' | 'portal', interval?: Interval) {
    setError(null)
    setBusy(action + (interval ?? ''))
    try {
      const { url } =
        action === 'checkout' ? await createCheckout(interval!) : await createPortal()
      window.location.href = url
    } catch (err) {
      setError(messageFor(err))
      setBusy(null)
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center gap-3">
        <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded-full bg-cyan-400/15 text-lg font-semibold text-cyan-300">
          {user.handle.charAt(0).toUpperCase()}
        </div>
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="truncate text-lg font-semibold text-zinc-100">{user.handle}</span>
            {user.pro && (
              <span className="rounded bg-amber-400/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
                Pro
              </span>
            )}
          </div>
          <div className="truncate text-sm text-zinc-500">{user.email}</div>
        </div>
      </div>

      <div className="rounded-xl border border-white/10 bg-[#0b0d12] p-5">
        <h2 className="text-sm font-semibold text-zinc-200">Subscription</h2>
        {user.pro ? (
          <>
            <p className="mt-1.5 text-sm text-zinc-500">
              You&apos;re on <span className="text-amber-300">Diamond Pro</span>. Manage or cancel
              anytime in the billing portal.
            </p>
            <button
              type="button"
              disabled={busy !== null}
              onClick={() => go('portal')}
              className="mt-4 rounded-lg border border-white/15 px-3 py-2 text-sm font-medium text-zinc-200 transition-colors hover:bg-white/5 disabled:opacity-60"
            >
              {busy === 'portal' ? 'Opening…' : 'Manage billing'}
            </button>
          </>
        ) : (
          <>
            <p className="mt-1.5 text-sm text-zinc-500">
              Upgrade to Diamond Pro to support the project. Cancel anytime.
            </p>
            <div className="mt-4 flex flex-wrap gap-2">
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => go('checkout', 'monthly')}
                className="rounded-lg bg-cyan-500 px-3 py-2 text-sm font-semibold text-[#06222b] transition-colors hover:bg-cyan-400 disabled:opacity-60"
              >
                {busy === 'checkoutmonthly' ? 'Redirecting…' : 'Go Pro — Monthly'}
              </button>
              <button
                type="button"
                disabled={busy !== null}
                onClick={() => go('checkout', 'annual')}
                className="rounded-lg border border-cyan-400/40 px-3 py-2 text-sm font-semibold text-cyan-300 transition-colors hover:bg-cyan-400/10 disabled:opacity-60"
              >
                {busy === 'checkoutannual' ? 'Redirecting…' : 'Go Pro — Annual'}
              </button>
            </div>
          </>
        )}
        {error && (
          <p className="mt-3 text-sm text-red-400" role="alert">
            {error}
          </p>
        )}
      </div>
    </div>
  )
}
