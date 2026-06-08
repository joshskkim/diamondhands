'use client'

import { createContext, useContext, useCallback } from 'react'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import {
  fetchMe,
  signIn as apiSignIn,
  signUp as apiSignUp,
  signOut as apiSignOut,
  type AuthUser,
} from '@/lib/api'

type AuthContextValue = {
  user: AuthUser | null
  isLoading: boolean
  signIn: (email: string, password: string) => Promise<void>
  signUp: (email: string, handle: string, password: string) => Promise<void>
  signOut: () => Promise<void>
}

const AuthContext = createContext<AuthContextValue | null>(null)
const ME_KEY = ['auth', 'me'] as const

/**
 * Exposes the current user (from `GET /api/auth/me`) and the auth actions. Each action hits the
 * API — which sets/clears the httpOnly session cookie — then primes the `me` query so the UI
 * updates immediately. Lives inside the QueryClientProvider (see app/layout.tsx).
 */
export function AuthProvider({ children }: { children: React.ReactNode }) {
  const qc = useQueryClient()

  const { data, isLoading } = useQuery({
    queryKey: ME_KEY,
    queryFn: fetchMe,
    staleTime: 5 * 60 * 1000,
    retry: false,
  })

  const signIn = useCallback(
    async (email: string, password: string) => {
      qc.setQueryData(ME_KEY, await apiSignIn({ email, password }))
    },
    [qc],
  )

  const signUp = useCallback(
    async (email: string, handle: string, password: string) => {
      qc.setQueryData(ME_KEY, await apiSignUp({ email, handle, password }))
    },
    [qc],
  )

  const signOut = useCallback(async () => {
    await apiSignOut()
    qc.setQueryData(ME_KEY, null)
  }, [qc])

  return (
    <AuthContext.Provider
      value={{ user: data ?? null, isLoading, signIn, signUp, signOut }}
    >
      {children}
    </AuthContext.Provider>
  )
}

export function useAuth() {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}
