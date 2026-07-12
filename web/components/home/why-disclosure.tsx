'use client'

import { useState, useRef, useEffect } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

/**
 * Collapsible reasoning for a pick card: leads with a compact "Why" toggle so the card
 * stays scannable (pick + numbers up front), and reveals the model's reasoning bullets
 * on demand. Renders nothing when there's no reasoning to show.
 *
 * The bullets open in a floating popover anchored to the toggle rather than expanding
 * the card inline — cards share a stretch grid row, so growing one inline would stretch
 * its neighbours too. The popover paints above sibling cards and dismisses on outside
 * click or Escape.
 */
export function WhyDisclosure({ reasons }: { reasons: string[] }) {
  const [open, setOpen] = useState(false)
  const ref = useRef<HTMLDivElement>(null)

  useEffect(() => {
    if (!open) return
    function onPointerDown(e: PointerEvent) {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false)
    }
    function onKey(e: KeyboardEvent) {
      if (e.key === 'Escape') setOpen(false)
    }
    document.addEventListener('pointerdown', onPointerDown)
    document.addEventListener('keydown', onKey)
    return () => {
      document.removeEventListener('pointerdown', onPointerDown)
      document.removeEventListener('keydown', onKey)
    }
  }, [open])

  if (reasons.length === 0) return null
  return (
    <div ref={ref} className="relative">
      <button
        type="button"
        onClick={() => setOpen((o) => !o)}
        aria-expanded={open}
        className="inline-flex items-center gap-1 text-[11px] uppercase tracking-[0.12em] font-medium text-zinc-500 hover:text-cyan-400 transition-colors"
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        Why {open ? '' : `(${reasons.length})`}
      </button>
      {open && (
        <div
          role="dialog"
          aria-label="Why the model likes this pick"
          className="absolute left-0 top-full z-20 mt-2 w-72 max-w-[calc(100vw-2rem)] rounded-lg border border-white/10 bg-[#0e1015] p-3 shadow-xl shadow-black/40"
        >
          <ul className="space-y-1.5 text-[13px] leading-relaxed text-zinc-400 list-disc pl-4 marker:text-zinc-600">
            {reasons.map((r, i) => (
              <li key={i}>{r}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  )
}
