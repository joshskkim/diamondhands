'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { User } from 'lucide-react'
import { cn } from '@/lib/utils'
import { SportSwitcher, type SportSwitcherItem } from './sport-switcher'

const MLB_ITEMS: readonly SportSwitcherItem[] = [
  { label: "Today's Board", href: '/mlb' },
  { label: 'Most Likely', href: '/mlb/most-likely' },
  { label: 'Best Lines', href: '/mlb/odds' },
  { label: 'Pitch Matchups', href: '/mlb/leaderboards/pitch-types' },
  { label: 'Accuracy', href: '/mlb/accuracy' },
]

const TENNIS_ITEMS: readonly SportSwitcherItem[] = [
  { label: 'Overview', href: '/tennis' },
  { label: 'Matches', href: '/tennis/matches' },
  { label: 'Rankings', href: '/tennis/rankings' },
]

const SECTION_LINKS = [
  { label: 'Best Bets', href: '/best-bets' },
  { label: 'Bet Trackers', href: '/trackers' },
  { label: 'Leaderboard', href: '/leaderboard' },
] as const

export function SiteNav() {
  const pathname = usePathname()

  return (
    <header className="sticky top-0 z-40 bg-[#0e1015]/80 backdrop-blur border-b border-white/10">
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center gap-6 overflow-x-auto">
        <Link
          href="/mlb"
          className="group inline-flex shrink-0 items-center gap-2 font-heading text-base font-semibold tracking-tight text-zinc-100"
        >
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full rounded-full bg-cyan-400/60 blur-[2px]" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.8)]" />
          </span>
          <span>Diamond</span>
        </Link>

        <nav className="flex shrink-0 items-center gap-5 text-sm font-medium">
          <SportSwitcher label="MLB" baseHref="/mlb" items={MLB_ITEMS} />
          <SportSwitcher label="Tennis" baseHref="/tennis" items={TENNIS_ITEMS} />

          <span className="h-4 w-px bg-white/10" aria-hidden />

          {SECTION_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                'whitespace-nowrap transition-colors',
                pathname.startsWith(link.href)
                  ? 'text-cyan-400'
                  : 'text-zinc-400 hover:text-zinc-100',
              )}
            >
              {link.label}
            </Link>
          ))}
        </nav>

        <Link
          href="/profile"
          className={cn(
            'ml-auto inline-flex shrink-0 items-center gap-1.5 text-sm font-medium transition-colors',
            pathname.startsWith('/profile')
              ? 'text-cyan-400'
              : 'text-zinc-400 hover:text-zinc-100',
          )}
        >
          <span className="inline-flex h-6 w-6 items-center justify-center rounded-full border border-white/10 bg-white/5">
            <User className="h-3.5 w-3.5" />
          </span>
          <span>Profile</span>
        </Link>
      </div>
    </header>
  )
}
