'use client'

import { useEffect, useId, useRef, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { Search, Loader2, X } from 'lucide-react'
import { playerSearchQueryOptions } from '@/lib/api'
import type { PlayerDetail } from '@/lib/types'
import { cn } from '@/lib/utils'

/**
 * Reusable player-name autocomplete over `/api/players/search`. Emits the chosen
 * player via `onSelect` and stays presentation-agnostic, so the same control
 * powers both the global nav search (→ navigate to the player) and the compare
 * page's "add a player" inputs (→ append to the comparison).
 */
export function PlayerSearch({
  onSelect,
  placeholder = 'Search players…',
  autoFocus = false,
  excludeIds,
  clearOnSelect = false,
  className,
}: {
  onSelect: (player: PlayerDetail) => void
  placeholder?: string
  autoFocus?: boolean
  /** Hide players already chosen elsewhere (e.g. already in the comparison). */
  excludeIds?: number[]
  /** Reset the input after a pick — used when adding to a list rather than navigating. */
  clearOnSelect?: boolean
  className?: string
}) {
  const [term, setTerm] = useState('')
  const [debounced, setDebounced] = useState('')
  const [open, setOpen] = useState(false)
  const [active, setActive] = useState(0)
  const containerRef = useRef<HTMLDivElement>(null)
  const listId = useId()

  // Debounce keystrokes so we hit the API at most every 200ms while typing.
  useEffect(() => {
    const id = setTimeout(() => setDebounced(term), 200)
    return () => clearTimeout(id)
  }, [term])

  const { data, isFetching } = useQuery(playerSearchQueryOptions(debounced))
  const exclude = new Set(excludeIds ?? [])
  const results = (data ?? []).filter((p) => !exclude.has(p.id))
  const showList = open && debounced.trim().length >= 2
  // Clamp the highlight into range as results shrink (reset to 0 happens on type).
  const activeIndex = results.length > 0 ? Math.min(active, results.length - 1) : 0

  // Close the dropdown on an outside click.
  useEffect(() => {
    if (!showList) return
    const onDown = (e: MouseEvent) => {
      if (containerRef.current && !containerRef.current.contains(e.target as Node)) {
        setOpen(false)
      }
    }
    document.addEventListener('mousedown', onDown)
    return () => document.removeEventListener('mousedown', onDown)
  }, [showList])

  function choose(p: PlayerDetail) {
    onSelect(p)
    setOpen(false)
    if (clearOnSelect) {
      setTerm('')
      setDebounced('')
    }
  }

  function onKeyDown(e: React.KeyboardEvent<HTMLInputElement>) {
    if (e.key === 'Escape') {
      setOpen(false)
      return
    }
    if (!showList || results.length === 0) return
    if (e.key === 'ArrowDown') {
      e.preventDefault()
      setActive((i) => (i + 1) % results.length)
    } else if (e.key === 'ArrowUp') {
      e.preventDefault()
      setActive((i) => (i - 1 + results.length) % results.length)
    } else if (e.key === 'Enter') {
      e.preventDefault()
      const pick = results[activeIndex]
      if (pick) choose(pick)
    }
  }

  return (
    <div ref={containerRef} className={cn('relative', className)}>
      <div className="flex items-center gap-2 rounded-lg border border-white/10 bg-white/5 px-3 transition-colors focus-within:border-cyan-400/40">
        {isFetching ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-cyan-400" />
        ) : (
          <Search className="h-4 w-4 shrink-0 text-zinc-500" />
        )}
        <input
          type="text"
          role="combobox"
          aria-expanded={showList}
          aria-controls={listId}
          aria-autocomplete="list"
          autoFocus={autoFocus}
          value={term}
          onChange={(e) => {
            setTerm(e.target.value)
            setActive(0)
            setOpen(true)
          }}
          onFocus={() => setOpen(true)}
          onKeyDown={onKeyDown}
          placeholder={placeholder}
          className="min-w-0 flex-1 bg-transparent py-2 text-sm text-zinc-100 placeholder:text-zinc-600 outline-none"
        />
        {term && (
          <button
            type="button"
            onClick={() => {
              setTerm('')
              setDebounced('')
            }}
            aria-label="Clear search"
            className="shrink-0 text-zinc-600 transition-colors hover:text-zinc-300"
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>

      {showList && (
        <ul
          id={listId}
          role="listbox"
          className="absolute z-50 mt-1.5 w-full overflow-hidden rounded-lg border border-white/10 bg-[#0e1015] shadow-2xl"
        >
          {results.length === 0 ? (
            <li className="px-3 py-3 text-sm text-zinc-500">
              {isFetching ? 'Searching…' : 'No players found.'}
            </li>
          ) : (
            results.map((p, i) => (
              <li key={p.id} role="option" aria-selected={i === activeIndex}>
                <button
                  type="button"
                  // mousedown (not click) so the pick lands before the input's blur closes the list.
                  onMouseDown={(e) => {
                    e.preventDefault()
                    choose(p)
                  }}
                  onMouseEnter={() => setActive(i)}
                  className={cn(
                    'flex w-full items-center gap-2 px-3 py-2.5 text-left transition-colors',
                    i === activeIndex ? 'bg-white/10' : 'hover:bg-white/5',
                  )}
                >
                  <span className="flex-1 truncate text-sm text-zinc-100">{p.fullName}</span>
                  <span className="shrink-0 font-mono text-xs text-zinc-500">
                    {[p.teamAbbr, p.position].filter(Boolean).join(' · ') || '—'}
                  </span>
                </button>
              </li>
            ))
          )}
        </ul>
      )}
    </div>
  )
}
