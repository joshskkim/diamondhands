'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { LayoutGrid, TrendingUp, Target, LineChart, Search, LogIn, LogOut, Menu, HelpCircle, Users, Sparkles, type LucideIcon } from 'lucide-react'
import { cn } from '@/lib/utils'
import { DiamondMark } from '@/components/diamond-mark'
import { GamesBadge } from '@/components/games-badge'
import { NavPlayerSearch } from '@/components/nav-player-search'
import { useAuth } from '@/components/auth-provider'

type NavLink = { label: string; href: string; icon: LucideIcon }

// Shared by the desktop rail and the mobile bottom nav so there's one source of
// truth for the primary navigation. The bottom nav shortens the labels for its
// tighter tabs (see mobile-nav.tsx).
export const NAV_LINKS: NavLink[] = [
  { label: "Today's Board", href: '/', icon: LayoutGrid },
  { label: 'Best Lines', href: '/mlb/odds', icon: TrendingUp },
  { label: 'Pitch Matchups', href: '/mlb/leaderboards/pitch-types', icon: Target },
  { label: 'Report Card', href: '/mlb/report-card', icon: LineChart },
]

// Secondary/help destinations shown on the desktop rail only. The mobile bottom
// bar stays at the four primary tabs; these live in its account sheet instead
// (see mobile-nav.tsx). Keep FAQ out of NAV_LINKS so it doesn't crowd that bar.
export const SECONDARY_LINKS: NavLink[] = [
  { label: 'Compare Players', href: '/mlb/players/compare', icon: Users },
  { label: 'FAQ', href: '/faq', icon: HelpCircle },
]

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
  onOpenSearch,
}: {
  collapsed?: boolean
  onNavigate?: () => void
  onToggleCollapse?: () => void
  onOpenSearch?: () => void
}) {
  const pathname = usePathname()
  const { user, signOut } = useAuth()

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
        {!collapsed && <GamesBadge />}
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

      {/* Ask Diamond search trigger (expanded: a search-bar button; collapsed: an icon) */}
      {onOpenSearch && (
        <div className={cn('pt-3', collapsed ? 'px-2' : 'px-4')}>
          {collapsed ? (
            <button
              type="button"
              onClick={onOpenSearch}
              title="Ask Diamond (⌘K)"
              aria-label="Ask Diamond"
              className="flex h-9 w-full items-center justify-center rounded-lg border border-white/10 bg-white/5 text-zinc-400 transition-colors hover:bg-white/10 hover:text-zinc-100"
            >
              <Search className="h-4 w-4" />
            </button>
          ) : (
            <button
              type="button"
              onClick={onOpenSearch}
              className="flex w-full items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 py-2 text-sm text-zinc-500 transition-colors hover:bg-white/10 hover:text-zinc-300"
            >
              <Search className="h-4 w-4 shrink-0" />
              <span className="flex-1 text-left">Ask Diamond…</span>
              <kbd className="rounded border border-white/10 px-1.5 py-0.5 text-[10px] text-zinc-500">⌘K</kbd>
            </button>
          )}
        </div>
      )}

      {/* Player name search — jumps straight to a player page (expanded rail only). */}
      {!collapsed && (
        <div className="px-4 pt-2">
          <NavPlayerSearch onNavigate={onNavigate} />
        </div>
      )}

      {/* nav */}
      <nav className="flex-1 px-2 py-3 space-y-1">
        {NAV_LINKS.map((link) => {
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

        {/* Diamond Analyst — the agent (requires sign-in), so only shown when authenticated. */}
        {user && (
          <Link
            href="/mlb/analyst"
            onClick={onNavigate}
            title={collapsed ? 'Diamond Analyst' : undefined}
            className={cn(
              'flex items-center gap-3 rounded-lg py-2 text-sm font-medium transition-colors',
              collapsed ? 'justify-center px-0' : 'px-3',
              isActive('/mlb/analyst')
                ? 'bg-cyan-400/10 text-cyan-400'
                : 'text-zinc-400 hover:text-zinc-100 hover:bg-white/5',
            )}
          >
            <Sparkles className="h-4 w-4 shrink-0" />
            {!collapsed && 'Diamond Analyst'}
          </Link>
        )}

        <div className="my-2 border-t border-white/10" />

        {SECONDARY_LINKS.map((link) => {
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
              <div className="flex min-w-0 flex-1 items-center gap-1.5 truncate text-sm font-medium text-zinc-200">
                <span className="truncate">{user.handle}</span>
                {user.pro && (
                  <span className="shrink-0 rounded bg-amber-400/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-amber-300">
                    Pro
                  </span>
                )}
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
