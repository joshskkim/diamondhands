'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { bestPlaysQueryOptions } from '@/lib/api'
import type { BestPlay } from '@/lib/types'
import { cn } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

const MARKET_LABEL: Record<string, string> = {
  moneyline: 'Moneyline',
  run_line: 'Run line',
  total: 'Total',
  hit: 'Hit',
  hr: 'Home run',
  pitcher_k: 'Strikeouts',
  pitcher_outs: 'Outs',
}

function amer(n: number) {
  return n > 0 ? `+${n}` : `${n}`
}

function pct(v: number) {
  return (v * 100).toFixed(1) + '%'
}

function evText(ev: number) {
  return (ev > 0 ? '+' : '') + (ev * 100).toFixed(1) + '%'
}

function evClass(ev: number) {
  if (ev > 0.05) return 'text-emerald-400 font-semibold'
  if (ev > 0) return 'text-emerald-300'
  if (ev > -0.05) return 'text-zinc-400'
  return 'text-rose-300'
}

// Positive-EV plays are the point of the board; let the user hide the rest.
type Filter = 'positive' | 'all'

export function OddsBoard() {
  const [filter, setFilter] = useState<Filter>('positive')
  const { data, isPending, isError } = useQuery(bestPlaysQueryOptions(undefined, 100))

  const rows: BestPlay[] = data ?? []
  const shown = filter === 'positive' ? rows.filter((r) => r.evPct > 0) : rows

  return (
    <main className="max-w-5xl mx-auto px-4 py-8">
      <div className={microLabel}>Odds</div>
      <h1 className="text-2xl font-bold tracking-tight text-zinc-100 mt-1 mb-2">Best Lines</h1>
      <p className="text-sm text-zinc-400 mb-5 max-w-2xl">
        Today&apos;s best available price for each market, ranked by{' '}
        <span className="text-zinc-200">EV</span> — our model probability times the best decimal
        odds, minus one. Positive EV means the best line on the board pays more than our model says
        it should. Game markets use a Poisson run model; hit/HR use the batter projections.
      </p>

      <div className="flex items-center gap-2 mb-4">
        <span className={microLabel}>Show</span>
        {(['positive', 'all'] as const).map((f) => (
          <button
            key={f}
            onClick={() => setFilter(f)}
            className={cn(
              'text-xs px-3 py-1 rounded border transition-colors',
              filter === f
                ? 'bg-cyan-500/15 text-cyan-300 border-cyan-400/40'
                : 'bg-white/5 text-zinc-400 border-white/10 hover:text-zinc-200 hover:border-white/20',
            )}
          >
            {f === 'positive' ? '+EV only' : 'All'}
          </button>
        ))}
      </div>

      {isPending ? (
        <p className="text-zinc-400">Loading odds…</p>
      ) : isError ? (
        <p className="text-rose-400">Failed to load odds.</p>
      ) : rows.length === 0 ? (
        <p className="text-amber-300 bg-amber-400/10 border border-amber-400/30 rounded-xl p-4 text-sm">
          No odds loaded yet. Run <span className="font-mono">refresh-odds</span> (needs{' '}
          <span className="font-mono">ODDS_API_KEY</span>, or{' '}
          <span className="font-mono">--sample</span> for fixtures).
        </p>
      ) : (
        <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className={microLabel}>
                <th className="px-3 py-2 text-left font-medium">Selection</th>
                <th className="px-3 py-2 text-left font-medium">Game</th>
                <th className="px-3 py-2 text-left font-medium">Market</th>
                <th className="px-3 py-2 text-right font-medium">Best line</th>
                <th className="px-3 py-2 text-right font-medium">Implied</th>
                <th className="px-3 py-2 text-right font-medium">Model</th>
                <th className="px-3 py-2 text-right font-medium">EV</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((r, i) => (
                <tr key={`${r.gameId}-${r.selection}-${i}`} className="border-t border-white/5">
                  <td className="px-3 py-2 text-zinc-100">
                    {r.playerId ? (
                      <Link href={`/players/${r.playerId}`} className="hover:text-cyan-400 transition-colors">
                        {r.selection}
                      </Link>
                    ) : (
                      r.selection
                    )}
                  </td>
                  <td className="px-3 py-2">
                    <Link
                      href={`/games/${r.gameId}`}
                      className="text-zinc-400 hover:text-cyan-400 transition-colors font-mono text-xs"
                    >
                      {r.matchup}
                    </Link>
                  </td>
                  <td className="px-3 py-2 text-zinc-400">{MARKET_LABEL[r.market] ?? r.market}</td>
                  <td className="px-3 py-2 text-right">
                    <span className="font-mono tabular-nums text-zinc-100">{amer(r.priceAmerican)}</span>{' '}
                    <span className="text-zinc-500 text-xs">{r.bestBook}</span>
                  </td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-400">{pct(r.impliedProb)}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">{pct(r.modelProb)}</td>
                  <td className={cn('px-3 py-2 text-right font-mono tabular-nums', evClass(r.evPct))}>
                    {evText(r.evPct)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {shown.length === 0 && (
            <p className="px-4 py-6 text-sm text-zinc-500">No positive-EV plays right now.</p>
          )}
        </div>
      )}
    </main>
  )
}
