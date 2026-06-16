'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutGrid, TrendingUp, Target, LineChart, Calendar, BarChart3, LogIn, LogOut, Menu, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DiamondMark } from '@/components/diamond-mark'
import { SportSwitcher } from '@/components/sport-switcher'
import { useAuth } from '@/components/auth-provider'

type NavLink = { label: string; href: string; icon: LucideIcon }

// Shared by the desktop rail and the mobile bottom nav so there's one source of
// truth for the primary navigation. The bottom nav shortens the labels for its
// tighter tabs (see mobile-nav.tsx). NAV_LINKS is the default (MLB) set; the
// nav is sport-aware via navLinksForPath().
export const NAV_LINKS: NavLink[] = [
  { label: "Today's Board", href: '/', icon: LayoutGrid },
  { label: 'Best Lines', href: '/mlb/odds', icon: TrendingUp },
  { label: 'Pitch Matchups', href: '/mlb/leaderboards/pitch-types', icon: Target },
  { label: 'Accuracy', href: '/mlb/accuracy', icon: LineChart },
]

export const TENNIS_NAV_LINKS: NavLink[] = [
  { label: 'Matches', href: '/tennis/matches', icon: Calendar },
  { label: 'Rankings', href: '/tennis/rankings', icon: BarChart3 },
  { label: 'Accuracy', href: '/tennis/accuracy', icon: LineChart },
]

/** Pick the nav set for the active sport (tennis routes vs everything else). */
export function navLinksForPath(pathname: string): NavLink[] {
  return pathname.startsWith('/tennis') ? TENNIS_NAV_LINKS : NAV_LINKS
}

// Sport switcher dropdown items (root of each sport).
export const SPORT_ITEMS = [
  { label: 'MLB', href: '/' },
  { label: 'Tennis', href: '/tennis/matches' },
] as const

/**
 * The inner content of the persistent side panel. Rendered both in the fixed
 * desktop rail and inside the mobile drawer (see app-shell.tsx). When
 * `collapsed`, only icons show (with title tooltips). `onNavigate` lets the
 * mobile drawer close itself when a link is tapped.
 */
export function AppSidebar({
  collapsed = false,
  onNavigate,
  onToggleCollapse,
}: {
  collapsed?: boolean
  onNavigate?: () => void
  onToggleCollapse?: () => void
}) {
  const pathname = usePathname()
  const { user, signOut } = useAuth()

  const isTennis = pathname.startsWith('/tennis')
  const navLinks = navLinksForPath(pathname)

  const isActive = (href: string) =>
    href === '/' ? pathname === '/' : pathname.startsWith(href)

  return (
    <div className="flex h-full flex-col">
      {/* brand + collapse toggle */}
      <div
        className={cn(
          'flex items-center h-14 shrink-0 border-b border-white/10',
          collapsed ? 'justify-center px-0' : 'px-4 gap-2',
        )}
      >
        {!collapsed && (
          <Link
            href="/"
            onClick={onNavigate}
            title="Diamond"
            className="flex items-center gap-2 font-semibold tracking-tight text-zinc-100"
          >
            <DiamondMark />
            <span className="text-base">Diamond</span>
          </Link>
        )}
        {onToggleCollapse && (
          <button
            type="button"
            onClick={onToggleCollapse}
            title={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            aria-label={collapsed ? 'Expand sidebar' : 'Collapse sidebar'}
            className={cn(
              'inline-flex h-7 w-7 items-center justify-center rounded-md text-zinc-400 hover:bg-white/5 hover:text-zinc-100 transition-colors',
              !collapsed && 'ml-auto',
            )}
          >
            <Menu className="h-4 w-4" />
          </button>
        )}
      </div>

      {/* sport switcher */}
      {!collapsed && (
        <div className="px-4 pt-3">
          <SportSwitcher
            label={isTennis ? 'Tennis' : 'MLB'}
            baseHref={isTennis ? '/tennis' : '/mlb'}
            items={SPORT_ITEMS}
          />
        </div>
      )}

      {/* nav */}
      <nav className="flex-1 px-2 py-3 space-y-1">
        {navLinks.map((link) => {
          const Icon = link.icon
          const active = isActive(link.href)
          return (
            <Link
              key={link.href}
              href={link.href}
              onClick={onNavigate}
              title={collapsed ? link.label : undefined}
              className={cn(
                'flex items-center gap-3 rounded-lg py-2 text-sm font-medium transition-colors',
                collapsed ? 'justify-center px-0' : 'px-3',
                active
                  ? 'bg-cyan-400/10 text-cyan-400'
                  : 'text-zinc-400 hover:text-zinc-100 hover:bg-white/5',
              )}
            >
              <Icon className="h-4 w-4 shrink-0" />
              {!collapsed && link.label}
            </Link>
          )
        })}
      </nav>

      {/* auth */}
      <div className="border-t border-white/10 p-3 shrink-0">
        {user ? (
          collapsed ? (
            <button
              type="button"
              onClick={() => {
                onNavigate?.()
                void signOut()
              }}
              title={`Sign out (${user.handle})`}
              aria-label="Sign out"
              className="flex h-9 w-full items-center justify-center rounded-lg text-zinc-400 transition-colors hover:bg-white/5 hover:text-zinc-100"
            >
              <LogOut className="h-4 w-4" />
            </button>
          ) : (
            <div className="flex items-center gap-2">
              <div className="flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-cyan-400/15 text-sm font-semibold text-cyan-300">
                {user.handle.charAt(0).toUpperCase()}
              </div>
              <div className="min-w-0 flex-1 truncate text-sm font-medium text-zinc-200">
                {user.handle}
              </div>
              <button
                type="button"
                onClick={() => {
                  onNavigate?.()
                  void signOut()
                }}
                title="Sign out"
                aria-label="Sign out"
                className="inline-flex h-7 w-7 shrink-0 items-center justify-center rounded-md text-zinc-400 transition-colors hover:bg-white/5 hover:text-zinc-100"
              >
                <LogOut className="h-4 w-4" />
              </button>
            </div>
          )
        ) : (
          <Link
            href="/signin"
            onClick={onNavigate}
            title={collapsed ? 'Sign up / Sign in' : undefined}
            className={cn(
              'flex h-9 w-full items-center justify-center rounded-lg border border-white/15 bg-white/5 text-sm font-medium text-zinc-200 transition-colors hover:bg-white/10 hover:text-zinc-100',
            )}
          >
            {collapsed ? <LogIn className="h-4 w-4" /> : 'Sign up / Sign in'}
          </Link>
        )}
      </div>
    </div>
  )
}
