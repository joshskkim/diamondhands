'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { cn } from '@/lib/utils'

const NAV_LINKS = [
  { label: "Today's Board", href: '/' },
  { label: 'Best Lines', href: '/odds' },
  { label: 'Pitch Matchups', href: '/leaderboards/pitch-types' },
] as const

export function SiteNav() {
  const pathname = usePathname()

  const isActive = (href: string) =>
    href === '/' ? pathname === '/' : pathname.startsWith(href)

  return (
    <header className="sticky top-0 z-40 bg-[#0e1015]/80 backdrop-blur border-b border-white/10">
      <div className="max-w-6xl mx-auto px-4 h-14 flex items-center justify-between">
        <Link
          href="/"
          className="group inline-flex items-center gap-2 font-semibold tracking-tight text-zinc-100"
        >
          <span className="relative flex h-2 w-2">
            <span className="absolute inline-flex h-full w-full rounded-full bg-cyan-400/60 blur-[2px]" />
            <span className="relative inline-flex h-2 w-2 rounded-full bg-cyan-400 shadow-[0_0_8px_rgba(34,211,238,0.8)]" />
          </span>
          <span className="text-base">Diamond</span>
        </Link>

        <nav className="flex items-center gap-6 text-sm font-medium">
          {NAV_LINKS.map((link) => (
            <Link
              key={link.href}
              href={link.href}
              className={cn(
                'transition-colors',
                isActive(link.href)
                  ? 'text-cyan-400'
                  : 'text-zinc-400 hover:text-zinc-100',
              )}
            >
              {link.label}
            </Link>
          ))}
        </nav>
      </div>
    </header>
  )
}
