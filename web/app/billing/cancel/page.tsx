import type { Metadata } from 'next'
import Link from 'next/link'

export const metadata: Metadata = { title: 'Checkout canceled' }

export default function BillingCancelPage() {
  return (
    <div className="max-w-6xl mx-auto w-full px-4 py-8">
      <div className="mx-auto max-w-md text-center">
        <div className="bg-[#0e1015] border border-white/10 rounded-xl p-8">
          <h1 className="text-2xl font-bold tracking-tight text-zinc-100">Checkout canceled</h1>
          <p className="text-zinc-500 text-sm mt-3">
            No charge was made. You can upgrade anytime from your profile.
          </p>
          <Link
            href="/profile"
            className="mt-6 inline-block rounded-lg border border-white/15 px-4 py-2 text-sm font-medium text-zinc-200 transition-colors hover:bg-white/5"
          >
            Back to profile
          </Link>
        </div>
      </div>
    </div>
  )
}
