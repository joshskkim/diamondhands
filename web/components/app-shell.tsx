'use client'

import { useEffect, useState, useSyncExternalStore } from 'react'
import Link from 'next/link'
import { Search } from 'lucide-react'
import { AppSidebar } from '@/components/app-sidebar'
import { AskSearch } from '@/components/ask-search'
import { MobileNav } from '@/components/mobile-nav'
import { DiamondMark } from '@/components/diamond-mark'
import { cn } from '@/lib/utils'

const COLLAPSE_KEY = 'diamond:sidebar-collapsed'

// Sidebar collapse is persisted in localStorage and read via an external store
// so SSR (expanded) hydrates cleanly to the client's saved choice without an
// effect-driven setState. Toggling dispatches a synthetic event to re-read.
function subscribeCollapse(cb: () => void) {
  window.addEventListener('storage', cb)
  return () => window.removeEventListener('storage', cb)
}

function useCollapsed(): [boolean, () => void] {
  const collapsed = useSyncExternalStore(
    subscribeCollapse,
    () => localStorage.getItem(COLLAPSE_KEY) === '1',
    () => false,
  )
  const toggle = () => {
    localStorage.setItem(COLLAPSE_KEY, collapsed ? '0' : '1')
    window.dispatchEvent(new Event('storage'))
  }
  return [collapsed, toggle]
}

/**
 * App layout shell: a persistent left rail on desktop (collapsible to icons-only,
 * choice persisted in localStorage) and a fixed bottom tab bar on mobile (see
 * MobileNav). Wraps every page so navigation stays put while routing.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [collapsed, toggleCollapsed] = useCollapsed()
  const [searchOpen, setSearchOpen] = useState(false)

  // Global ⌘K / Ctrl+K opens the Ask Diamond search palette.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
        e.preventDefault()
        setSearchOpen(true)
      }
    }
    window.addEventListener('keydown', onKey)
    return () => window.removeEventListener('keydown', onKey)
  }, [])

  return (
    <div className="flex min-h-screen">
      {/* desktop rail */}
      <aside
        className={cn(
          'hidden md:flex md:flex-col shrink-0 sticky top-0 h-screen bg-[#0e1015] border-r border-white/10',
          collapsed ? 'w-16' : 'w-60',
        )}
      >
        <div className="flex-1 min-h-0">
          <AppSidebar
            collapsed={collapsed}
            onToggleCollapse={toggleCollapsed}
            onOpenSearch={() => setSearchOpen(true)}
          />
        </div>
      </aside>

      <div className="flex flex-1 min-w-0 flex-col">
        {/* mobile top bar — brand + search; primary navigation lives in the bottom bar */}
        <header className="md:hidden sticky top-0 z-40 flex items-center h-12 px-4 bg-[#0e1015]/80 backdrop-blur border-b border-white/10">
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight text-zinc-100">
            <DiamondMark />
            <span className="text-base">Diamond</span>
          </Link>
          <button
            type="button"
            onClick={() => setSearchOpen(true)}
            aria-label="Ask Diamond"
            className="ml-auto inline-flex h-8 w-8 items-center justify-center rounded-md text-zinc-400 transition-colors hover:bg-white/5 hover:text-zinc-100"
          >
            <Search className="h-4 w-4" />
          </button>
        </header>

        {/* pb-20 keeps content clear of the fixed bottom nav on mobile */}
        <main className="flex-1 min-w-0 pb-20 md:pb-0">{children}</main>
      </div>

      {/* mobile bottom nav (self-gates to md:hidden) */}
      <MobileNav />

      {/* global Ask Diamond search palette (⌘K) */}
      {searchOpen && <AskSearch onClose={() => setSearchOpen(false)} />}
    </div>
  )
}
