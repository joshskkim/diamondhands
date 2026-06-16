'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { useState } from 'react'
import { CircleUserRound, LogIn, LogOut, Trophy, X } from 'lucide-react'
import { navLinksForPath } from '@/components/app-sidebar'
import { useAuth } from '@/components/auth-provider'
import { DiamondMark } from '@/components/diamond-mark'
import { cn } from '@/lib/utils'

// The bottom bar is tight, so the primary nav uses shorter labels than the
// desktop rail. Keyed by href back to the shared NAV_LINKS.
const SHORT_LABEL: Record<string, string> = {
  '/': 'Board',
  '/mlb/odds': 'Lines',
  '/mlb/leaderboards/pitch-types': 'Matchups',
  '/mlb/accuracy': 'Accuracy',
  '/tennis/matches': 'Matches',
  '/tennis/rankings': 'Rankings',
  '/tennis/accuracy': 'Accuracy',
}

// Secondary destinations that don't earn a bottom-bar tab live in the account sheet.
const SHEET_LINKS: { label: string; href: string }[] = [
  { label: 'Leaderboards', href: '/leaderboard' },
]

const tabClass = (active: boolean) =>
  cn(
    'flex flex-1 flex-col items-center justify-center gap-0.5 py-1.5 text-[10px] font-medium transition-colors',
    active ? 'text-cyan-400' : 'text-zinc-500 hover:text-zinc-300',
  )

/**
 * Fixed bottom tab bar for mobile (hidden at md+). Four primary nav tabs share
 * NAV_LINKS with the desktop rail; the fifth "Account" tab opens a bottom sheet
 * with the auth controls (mirroring the rail's auth block) plus secondary links.
 */
export function MobileNav() {
  const pathname = usePathname()
  const [sheetOpen, setSheetOpen] = useState(false)
  const { user, signOut } = useAuth()

  const navLinks = navLinksForPath(pathname)

  const isActive = (href: string) =>
    href === '/' ? pathname === '/' : pathname.startsWith(href)

  return (
    <>
      <nav
        className="fixed inset-x-0 bottom-0 z-40 flex border-t border-white/10 bg-[#0e1015]/95 backdrop-blur md:hidden"
        style={{ paddingBottom: 'env(safe-area-inset-bottom)' }}
      >
        {navLinks.map((link) => {
          const Icon = link.icon
          const active = isActive(link.href)
          return (
            <Link key={link.href} href={link.href} className={tabClass(active)}>
              <Icon className="h-5 w-5" />
              {SHORT_LABEL[link.href] ?? link.label}
            </Link>
          )
        })}
        <button
          type="button"
          onClick={() => setSheetOpen(true)}
          aria-label="Account"
          className={tabClass(sheetOpen)}
        >
          <CircleUserRound className="h-5 w-5" />
          Account
        </button>
      </nav>

      {sheetOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div
            className="absolute inset-0 bg-black/60"
            onClick={() => setSheetOpen(false)}
            aria-hidden
          />
          <div
            className="absolute inset-x-0 bottom-0 rounded-t-2xl border-t border-white/10 bg-[#0e1015] p-4"
            style={{ paddingBottom: 'calc(env(safe-area-inset-bottom) + 1rem)' }}
          >
            <div className="mb-4 flex items-center justify-between">
              <div className="flex items-center gap-2 font-semibold tracking-tight text-zinc-100">
                <DiamondMark />
                <span className="text-base">Diamond</span>
              </div>
              <button
                type="button"
                onClick={() => setSheetOpen(false)}
                aria-label="Close"
                className="inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-400 hover:bg-white/5 hover:text-zinc-100"
              >
                <X className="h-4 w-4" />
              </button>
            </div>

            {/* auth — mirrors the desktop rail's auth block */}
            {user ? (
              <div className="flex items-center gap-3 rounded-lg border border-white/10 bg-white/5 p-3">
                <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-cyan-400/15 text-sm font-semibold text-cyan-300">
                  {user.handle.charAt(0).toUpperCase()}
                </div>
                <div className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-200">
                  {user.handle}
                </div>
                <button
                  type="button"
                  onClick={() => {
                    setSheetOpen(false)
                    void signOut()
                  }}
                  className="inline-flex items-center gap-1.5 rounded-md px-2.5 py-1.5 text-sm text-zinc-400 transition-colors hover:bg-white/5 hover:text-zinc-100"
                >
                  <LogOut className="h-4 w-4" />
                  Sign out
                </button>
              </div>
            ) : (
              <Link
                href="/signin"
                onClick={() => setSheetOpen(false)}
                className="flex h-11 w-full items-center justify-center gap-2 rounded-lg border border-white/15 bg-white/5 text-sm font-medium text-zinc-200 transition-colors hover:bg-white/10 hover:text-zinc-100"
              >
                <LogIn className="h-4 w-4" />
                Sign up / Sign in
              </Link>
            )}

            {/* secondary links */}
            <div className="mt-3 space-y-1">
              {SHEET_LINKS.map((link) => (
                <Link
                  key={link.href}
                  href={link.href}
                  onClick={() => setSheetOpen(false)}
                  className="flex items-center gap-2 rounded-lg px-3 py-2.5 text-sm font-medium text-zinc-300 transition-colors hover:bg-white/5 hover:text-zinc-100"
                >
                  <Trophy className="h-4 w-4 text-zinc-500" />
                  {link.label}
                </Link>
              ))}
            </div>
          </div>
        </div>
      )}
    </>
  )
}
