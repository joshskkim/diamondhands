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

function pct(v: number | null) {
  if (v == null) return '—'
  return (v * 100).toFixed(1) + '%'
}

function signedPct(v: number) {
  return (v > 0 ? '+' : '') + (v * 100).toFixed(1) + '%'
}

// Edge = model − fair (no-vig). This is the board's headline metric; positive means our
// model gives the side a better chance than the de-vigged market does.
function edgeOf(r: BestPlay): number | null {
  return r.fairProb == null ? null : r.modelProb - r.fairProb
}

function edgeClass(edge: number | null) {
  if (edge == null) return 'text-zinc-600'
  if (edge > 0.03) return 'text-emerald-400 font-semibold'
  if (edge > 0) return 'text-emerald-300'
  if (edge > -0.03) return 'text-zinc-400'
  return 'text-rose-300'
}

function evClass(ev: number) {
  if (ev > 0.05) return 'text-emerald-400'
  if (ev > 0) return 'text-emerald-300'
  if (ev > -0.05) return 'text-zinc-500'
  return 'text-rose-300/80'
}

// "AWY @ HOM" → team abbr for a home/away side.
function teamForSide(matchup: string, side: string): string {
  const parts = matchup.split(' @ ')
  if (parts.length !== 2) return side
  return side === 'home' ? parts[1] : parts[0]
}

function sideLabel(r: BestPlay): { text: string; tone: 'over' | 'under' | 'team' } {
  if (r.side === 'over') return { text: 'Over', tone: 'over' }
  if (r.side === 'under') return { text: 'Under', tone: 'under' }
  return { text: teamForSide(r.matchup, r.side), tone: 'team' }
}

function lineLabel(r: BestPlay): string {
  if (r.line == null) return '—'
  if (r.market === 'run_line' && r.line > 0) return `+${r.line}`
  return `${r.line}`
}

// Player props → the player; game markets → the matchup.
function subject(r: BestPlay): string {
  return r.playerName ?? r.matchup
}

const SIDE_TONE: Record<'over' | 'under' | 'team', string> = {
  over: 'bg-emerald-500/10 text-emerald-300 border-emerald-400/30',
  under: 'bg-amber-500/10 text-amber-300 border-amber-400/30',
  team: 'bg-cyan-500/10 text-cyan-300 border-cyan-400/30',
}

// Positive-edge plays are the point of the board; let the user hide the rest.
type Filter = 'positive' | 'all'

export function OddsBoard() {
  const [filter, setFilter] = useState<Filter>('positive')
  const { data, isPending, isError } = useQuery(bestPlaysQueryOptions(undefined, 100))

  const rows: BestPlay[] = data ?? []
  const shown = filter === 'positive' ? rows.filter((r) => (edgeOf(r) ?? r.evPct) > 0) : rows

  return (
    <main className="max-w-6xl mx-auto px-4 py-8">
      <div className={microLabel}>Odds</div>
      <h1 className="text-2xl font-bold tracking-tight text-zinc-100 mt-1 mb-2">Best Lines</h1>
      <p className="text-sm text-zinc-400 mb-5 max-w-2xl">
        Today&apos;s best available price for each market, ranked by{' '}
        <span className="text-zinc-200">edge</span> — our model probability minus the{' '}
        <span className="text-zinc-200">fair</span> (no-vig) market probability. We strip the
        bookmaker&apos;s margin out of both sides before comparing, so a juiced favorite no longer
        makes its opposite side look like free money. Game markets use a Poisson run model; hit/HR
        use the batter projections.
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
            {f === 'positive' ? '+Edge only' : 'All'}
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
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={microLabel}>
                  <th className="px-3 py-2 text-left font-medium">Player / Game</th>
                  <th className="px-3 py-2 text-left font-medium">Type</th>
                  <th className="px-3 py-2 text-left font-medium">Side</th>
                  <th className="px-3 py-2 text-right font-medium">Line</th>
                  <th className="px-3 py-2 text-right font-medium">Best price</th>
                  <th className="px-3 py-2 text-right font-medium" title="No-vig market probability">
                    Fair
                  </th>
                  <th className="px-3 py-2 text-right font-medium">Model</th>
                  <th className="px-3 py-2 text-right font-medium" title="Model − Fair">
                    Edge
                  </th>
                  <th className="px-3 py-2 text-right font-medium" title="Expected value at the best price">
                    EV
                  </th>
                </tr>
              </thead>
              <tbody>
                {shown.map((r, i) => {
                  const s = sideLabel(r)
                  const edge = edgeOf(r)
                  return (
                    <tr
                      key={`${r.gameId}-${r.market}-${r.selection}-${i}`}
                      className="border-t border-white/5 hover:bg-white/[0.02] transition-colors"
                    >
                      <td className="px-3 py-2 text-zinc-100 whitespace-nowrap">
                        {r.playerId ? (
                          <Link href={`/mlb/players/${r.playerId}`} className="hover:text-cyan-400 transition-colors">
                            {subject(r)}
                          </Link>
                        ) : (
                          <Link href={`/mlb/games/${r.gameId}`} className="hover:text-cyan-400 transition-colors">
                            {subject(r)}
                          </Link>
                        )}
                        {r.playerName && (
                          <Link
                            href={`/mlb/games/${r.gameId}`}
                            className="text-zinc-500 hover:text-cyan-400 transition-colors font-mono text-xs ml-1.5"
                          >
                            {r.matchup}
                          </Link>
                        )}
                      </td>
                      <td className="px-3 py-2 text-zinc-300 whitespace-nowrap">
                        {MARKET_LABEL[r.market] ?? r.market}
                      </td>
                      <td className="px-3 py-2">
                        <span
                          className={cn(
                            'inline-block px-1.5 py-0.5 rounded border text-xs font-medium',
                            SIDE_TONE[s.tone],
                          )}
                        >
                          {s.text}
                        </span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">
                        {lineLabel(r)}
                      </td>
                      <td className="px-3 py-2 text-right whitespace-nowrap">
                        <span className="font-mono tabular-nums text-zinc-100">{amer(r.priceAmerican)}</span>{' '}
                        <span className="text-zinc-500 text-xs">{r.bestBook}</span>
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-400">
                        {pct(r.fairProb)}
                      </td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">
                        {pct(r.modelProb)}
                      </td>
                      <td className={cn('px-3 py-2 text-right font-mono tabular-nums', edgeClass(edge))}>
                        {edge == null ? '—' : signedPct(edge)}
                      </td>
                      <td className={cn('px-3 py-2 text-right font-mono tabular-nums text-xs', evClass(r.evPct))}>
                        {signedPct(r.evPct)}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
          {shown.length === 0 && (
            <p className="px-4 py-6 text-sm text-zinc-500">No positive-edge plays right now.</p>
          )}
        </div>
      )}
    </main>
  )
}
