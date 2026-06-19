'use client'

import { useState } from 'react'
import { ChevronDown, ChevronRight } from 'lucide-react'

/**
 * Collapsible reasoning for a pick card: leads with a compact "Why" toggle so the card
 * stays scannable (pick + numbers up front), and reveals the model's reasoning bullets
 * on demand. Renders nothing when there's no reasoning to show.
 */
export function WhyDisclosure({ reasons }: { reasons: string[] }) {
  const [open, setOpen] = useState(false)
  if (reasons.length === 0) return null
  return (
    <div>
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
        <ul className="mt-2 space-y-1.5 text-[13px] leading-relaxed text-zinc-400 list-disc pl-4 marker:text-zinc-600">
          {reasons.map((r, i) => (
            <li key={i}>{r}</li>
          ))}
        </ul>
      )}
    </div>
  )
}
