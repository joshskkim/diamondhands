'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { History } from 'lucide-react'
import { format } from 'date-fns'
import { modelPicksQueryOptions } from '@/lib/api'
import type { ModelPickResult } from '@/lib/types'
import { cn } from '@/lib/utils'
import { easternDateStr, pickOutcome, pickTitle } from '@/lib/picks'
import { OutcomeBadge } from './outcome-badge'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

// The actual result phrased per market — what the pick was graded against.
function resultLabel(p: ModelPickResult): string | null {
  if (p.resultValue == null) return null
  switch (p.market) {
    case 'total':
      return `${p.resultValue} total runs`
    case 'moneyline':
    case 'run_line':
      return `${p.resultValue > 0 ? '+' : ''}${p.resultValue} run margin`
    case 'hit':
      return `${p.resultValue} hit${p.resultValue === 1 ? '' : 's'}`
    case 'hr':
      return `${p.resultValue} HR`
    default:
      return `${p.resultValue}`
  }
}

function ResultRow({ p }: { p: ModelPickResult }) {
  const outcome = pickOutcome(p)
  const result = resultLabel(p)
  return (
    <div className="flex items-center gap-3 rounded-lg border border-white/10 bg-[#0e1015] px-4 py-2.5">
      <OutcomeBadge outcome={outcome} />
      <div className="min-w-0 flex-1">
        <div className="flex items-center gap-1.5">
          {p.lotto && (
            <span className="shrink-0 text-[9px] uppercase tracking-[0.12em] font-semibold px-1 py-0.5 rounded border text-amber-300 border-amber-400/40 bg-amber-500/10">
              Lotto
            </span>
          )}
          <span className="truncate text-sm text-zinc-200">{pickTitle(p)}</span>
        </div>
        <div className="text-xs text-zinc-500">
          Model {(p.modelProb * 100).toFixed(0)}%
          {result != null && <> · actual {result}</>}
        </div>
      </div>
      <Link
        href={`/mlb/games/${p.gameId}`}
        className="shrink-0 font-mono text-xs text-zinc-500 transition-colors hover:text-cyan-400"
      >
        {p.matchup}
      </Link>
    </div>
  )
}

/**
 * Recent results: yesterday's recorded Model's Picks with their graded ✓/✗ outcomes —
 * the running track record. Hidden entirely until a prior slate has graded picks.
 */
export function RecentResults() {
  const slate = easternDateStr(-1)
  const { data } = useQuery(modelPicksQueryOptions(slate))
  const picks = data ?? []
  // Only show once at least one pick has settled (avoids an empty/all-pending strip).
  const settled = picks.filter((p) => p.scored)
  if (settled.length === 0) return null

  // The high-variance lotto is excluded from the disciplined track record (it
  // still renders, tagged, so its result is visible).
  const disciplined = settled.filter((p) => !p.lotto)
  const won = disciplined.filter((p) => p.won === true).length
  const lost = disciplined.filter((p) => p.won === false).length

  return (
    <section className="mb-10">
      <div className="mb-3">
        <h2 className="flex items-center gap-1.5 text-sm font-semibold tracking-tight text-zinc-100">
          <History className="h-4 w-4 text-cyan-300" aria-hidden="true" />
          Recent Results
        </h2>
        <p className={cn(microLabel, 'mt-0.5 normal-case tracking-normal')}>
          {format(new Date(`${slate}T00:00:00`), 'EEEE, MMM d')}&apos;s picks, graded —{' '}
          <span className="text-emerald-300">{won} hit</span> ·{' '}
          <span className="text-rose-300">{lost} miss</span>
        </p>
      </div>
      <div className="grid gap-2">
        {picks.map((p) => (
          <ResultRow key={`${p.gameId}-${p.market}-${p.rank}`} p={p} />
        ))}
      </div>
    </section>
  )
}
