'use client'

import { useEffect, useRef, useState } from 'react'
import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { ChevronDown } from 'lucide-react'
import { cn } from '@/lib/utils'

export type SportSwitcherItem = {
  label: string
  href: string
}

type SportSwitcherProps = {
  /** Display label for the sport (e.g. "MLB"). */
  label: string
  /** Base href; the sport is "active" when the pathname starts with this. */
  baseHref: string
  /** Dropdown menu items. */
  items: readonly SportSwitcherItem[]
}

export function SportSwitcher({ label, baseHref, items }: SportSwitcherProps) {
  const pathname = usePathname()
  const [open, setOpen] = useState(false)
  const [lastPathname, setLastPathname] = useState(pathname)
  const containerRef = useRef<HTMLDivElement>(null)

  // Close on route change — reset during render instead of in an effect to
  // avoid the cascading-render lint rule (react-hooks/set-state-in-effect).
  if (pathname !== lastPathname) {
    setLastPathname(pathname)
    setOpen(false)
  }

  const isActiveSport = pathname.startsWith(baseHref)

  // Close on outside click.
  useEffect(() => {
    if (!open) return
    function onPointerDown(event: MouseEvent) {
      if (
        containerRef.current &&
        !containerRef.current.contains(event.target as Node)
      ) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onPointerDown)
    return () => document.removeEventListener('mousedown', onPointerDown)
  }, [open])

  return (
    <div ref={containerRef} className="relative">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-haspopup="menu"
        aria-expanded={open}
        className={cn(
          'inline-flex items-center gap-1 font-heading text-sm font-medium tracking-tight transition-colors',
          isActiveSport
            ? 'text-cyan-400'
            : 'text-zinc-400 hover:text-zinc-100',
        )}
      >
        {label}
        <ChevronDown
          className={cn(
            'h-3.5 w-3.5 transition-transform',
            open && 'rotate-180',
          )}
        />
      </button>

      {open && (
        <div
          role="menu"
          className="absolute left-0 top-full z-50 mt-2 min-w-44 overflow-hidden rounded-xl border border-white/10 bg-[#0e1015] py-1 shadow-xl shadow-black/40"
        >
          {items.map((item) => {
            const active =
              item.href === baseHref
                ? pathname === baseHref
                : pathname.startsWith(item.href)
            return (
              <Link
                key={item.href}
                href={item.href}
                role="menuitem"
                className={cn(
                  'block px-3 py-2 text-sm transition-colors',
                  active
                    ? 'text-cyan-400'
                    : 'text-zinc-400 hover:bg-white/5 hover:text-zinc-100',
                )}
              >
                {item.label}
              </Link>
            )
          })}
        </div>
      )}
    </div>
  )
}
