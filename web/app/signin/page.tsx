import type { Metadata } from 'next'
import { SignInForm } from './signin-form'
import { microLabel } from '@/components/ui/primitives'

export const metadata: Metadata = {
  title: 'Sign in',
}

export default function SignInPage() {
  return (
    <div className="max-w-6xl mx-auto w-full px-4 py-8">
      <div className="mx-auto max-w-md">
        <div className="bg-[#0e1015] border border-white/10 rounded-xl p-8">
          <div className="text-center">
            <div className={microLabel}>
              Accounts
            </div>
            <h1 className="text-2xl font-bold tracking-tight text-zinc-100 mt-2">
              Sign up / Sign in
            </h1>
            <p className="text-zinc-500 text-sm mt-3">
              Save picks, track your board, and sync across devices.
            </p>
          </div>
          <SignInForm />
        </div>
      </div>
    </div>
  )
}
