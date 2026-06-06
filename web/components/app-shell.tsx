'use client'

import { useState, useSyncExternalStore } from 'react'
import Link from 'next/link'
import { Menu, X } from 'lucide-react'
import { AppSidebar } from '@/components/app-sidebar'
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
 * choice persisted in localStorage) and a slide-in drawer on mobile. Wraps every
 * page so the side panel stays put while navigating.
 */
export function AppShell({ children }: { children: React.ReactNode }) {
  const [drawerOpen, setDrawerOpen] = useState(false)
  const [collapsed, toggleCollapsed] = useCollapsed()
  const closeDrawer = () => setDrawerOpen(false)

  return (
    <div className="flex min-h-screen">
      {/* desktop rail */}
      <aside
        className={cn(
          'hidden md:flex md:flex-col shrink-0 sticky top-0 h-screen bg-[#0e1015] border-r border-white/10 transition-[width] duration-200',
          collapsed ? 'w-16' : 'w-60',
        )}
      >
        <div className="flex-1 min-h-0">
          <AppSidebar collapsed={collapsed} onToggleCollapse={toggleCollapsed} />
        </div>
      </aside>

      {/* mobile drawer */}
      {drawerOpen && (
        <div className="fixed inset-0 z-50 md:hidden">
          <div className="absolute inset-0 bg-black/60" onClick={closeDrawer} aria-hidden />
          <aside className="absolute inset-y-0 left-0 w-64 bg-[#0e1015] border-r border-white/10 shadow-xl">
            <AppSidebar onNavigate={closeDrawer} />
          </aside>
        </div>
      )}

      <div className="flex flex-1 min-w-0 flex-col">
        {/* mobile top bar */}
        <header className="md:hidden sticky top-0 z-40 flex items-center gap-3 h-14 px-4 bg-[#0e1015]/80 backdrop-blur border-b border-white/10">
          <button
            type="button"
            onClick={() => setDrawerOpen((v) => !v)}
            aria-label={drawerOpen ? 'Close menu' : 'Open menu'}
            className="inline-flex h-9 w-9 items-center justify-center rounded-lg text-zinc-300 hover:bg-white/5 hover:text-zinc-100"
          >
            {drawerOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
          </button>
          <Link href="/" className="flex items-center gap-2 font-semibold tracking-tight text-zinc-100">
            <DiamondMark />
            <span className="text-base">Diamond</span>
          </Link>
        </header>

        <main className="flex-1 min-w-0">{children}</main>
      </div>
    </div>
  )
}
