'use client'

import { useState, type FormEvent } from 'react'
import { useRouter } from 'next/navigation'
import { useAuth } from '@/components/auth-provider'
import { ApiError } from '@/lib/api'

type Mode = 'signin' | 'signup'

function messageFor(err: unknown, mode: Mode): string {
  if (err instanceof ApiError) {
    if (err.status === 401) return 'Invalid email or password.'
    if (err.status === 409) return 'That email or handle is already taken.'
    if (err.status === 400)
      return mode === 'signup'
        ? 'Check your details: handle is 3–20 letters/numbers/underscores, password 8+ characters.'
        : 'Enter a valid email and password.'
  }
  return 'Something went wrong. Please try again.'
}

const inputClass =
  'w-full rounded-lg border border-white/10 bg-[#0b0d12] px-3 py-2 text-sm text-zinc-100 ' +
  'placeholder:text-zinc-600 focus:border-cyan-400/50 focus:outline-none focus:ring-1 focus:ring-cyan-400/40'

export function SignInForm() {
  const router = useRouter()
  const { signIn, signUp } = useAuth()
  const [mode, setMode] = useState<Mode>('signin')
  const [email, setEmail] = useState('')
  const [handle, setHandle] = useState('')
  const [password, setPassword] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [submitting, setSubmitting] = useState(false)

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    setSubmitting(true)
    try {
      if (mode === 'signup') await signUp(email, handle, password)
      else await signIn(email, password)
      router.push('/')
      router.refresh()
    } catch (err) {
      setError(messageFor(err, mode))
      setSubmitting(false)
    }
  }

  function switchMode(next: Mode) {
    setMode(next)
    setError(null)
  }

  return (
    <form onSubmit={onSubmit} className="mt-6 space-y-3 text-left">
      <div className="space-y-1.5">
        <label htmlFor="email" className="text-xs font-medium text-zinc-400">
          Email
        </label>
        <input
          id="email"
          type="email"
          autoComplete="email"
          required
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          className={inputClass}
          placeholder="you@example.com"
        />
      </div>

      {mode === 'signup' && (
        <div className="space-y-1.5">
          <label htmlFor="handle" className="text-xs font-medium text-zinc-400">
            Handle <span className="text-zinc-600">(public, shown on leaderboards)</span>
          </label>
          <input
            id="handle"
            type="text"
            autoComplete="username"
            required
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            className={inputClass}
            placeholder="slugger_42"
          />
        </div>
      )}

      <div className="space-y-1.5">
        <label htmlFor="password" className="text-xs font-medium text-zinc-400">
          Password
        </label>
        <input
          id="password"
          type="password"
          autoComplete={mode === 'signup' ? 'new-password' : 'current-password'}
          required
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          className={inputClass}
          placeholder={mode === 'signup' ? 'At least 8 characters' : '••••••••'}
        />
      </div>

      {error && (
        <p className="text-sm text-red-400" role="alert">
          {error}
        </p>
      )}

      <button
        type="submit"
        disabled={submitting}
        className="w-full rounded-lg bg-cyan-500 px-3 py-2 text-sm font-semibold text-[#06222b] transition-colors hover:bg-cyan-400 disabled:opacity-60"
      >
        {submitting
          ? 'Please wait…'
          : mode === 'signup'
            ? 'Create account'
            : 'Sign in'}
      </button>

      <p className="pt-1 text-center text-sm text-zinc-500">
        {mode === 'signup' ? (
          <>
            Already have an account?{' '}
            <button
              type="button"
              onClick={() => switchMode('signin')}
              className="font-medium text-cyan-400 hover:text-cyan-300"
            >
              Sign in
            </button>
          </>
        ) : (
          <>
            New here?{' '}
            <button
              type="button"
              onClick={() => switchMode('signup')}
              className="font-medium text-cyan-400 hover:text-cyan-300"
            >
              Create an account
            </button>
          </>
        )}
      </p>
    </form>
  )
}
