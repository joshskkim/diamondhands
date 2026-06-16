'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { tennisRankingsQueryOptions } from '@/lib/tennis-api'
import { cn } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'
const SURFACES = ['all', 'hard', 'clay', 'grass'] as const

function num(v: number | null, digits = 0): string {
  return v == null ? '—' : v.toFixed(digits)
}
function pct(v: number | null): string {
  return v == null ? '—' : (v * 100).toFixed(1) + '%'
}

export function TennisRankingsBoard() {
  const [surface, setSurface] = useState<(typeof SURFACES)[number]>('all')
  const { data, isLoading, isError } = useQuery(tennisRankingsQueryOptions(surface))

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8">
      <p className={microLabel}>ATP · Surface-blended Elo</p>
      <h1 className="mt-1 text-3xl text-zinc-100">Rankings</h1>

      <div className="mt-4 flex gap-1.5">
        {SURFACES.map((s) => (
          <button
            key={s}
            type="button"
            onClick={() => setSurface(s)}
            className={cn(
              'rounded-lg border px-3 py-1.5 text-sm capitalize transition-colors',
              surface === s
                ? 'border-cyan-400/40 bg-cyan-400/10 text-cyan-400'
                : 'border-white/10 bg-[#0e1015] text-zinc-400 hover:text-zinc-100',
            )}
          >
            {s}
          </button>
        ))}
      </div>

      <div className="mt-5 overflow-hidden rounded-xl border border-white/10">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-b border-white/10 bg-white/[0.02] text-left">
              <th className="px-3 py-2 text-[10px] font-medium uppercase tracking-wider text-zinc-500">#</th>
              <th className="px-3 py-2 text-[10px] font-medium uppercase tracking-wider text-zinc-500">Player</th>
              <th className="hidden px-3 py-2 text-right text-[10px] font-medium uppercase tracking-wider text-zinc-500 sm:table-cell">Age</th>
              <th className="px-3 py-2 text-right text-[10px] font-medium uppercase tracking-wider text-zinc-500">Elo</th>
              <th className="px-3 py-2 text-right text-[10px] font-medium uppercase tracking-wider text-zinc-500">SPW</th>
              <th className="hidden px-3 py-2 text-right text-[10px] font-medium uppercase tracking-wider text-zinc-500 sm:table-cell">Matches</th>
            </tr>
          </thead>
          <tbody>
            {isLoading && (
              <tr><td colSpan={6} className="px-3 py-4 text-zinc-500">Loading…</td></tr>
            )}
            {isError && (
              <tr><td colSpan={6} className="px-3 py-4 text-rose-400">Couldn&apos;t load rankings.</td></tr>
            )}
            {data?.map((r) => (
              <tr key={r.player.id} className="border-b border-white/5 last:border-0 hover:bg-white/[0.02]">
                <td className="px-3 py-2 font-mono text-zinc-500">{r.rank}</td>
                <td className="px-3 py-2 text-zinc-100">
                  {r.player.name}
                  {r.player.country && <span className="ml-1.5 text-[10px] text-zinc-600">{r.player.country}</span>}
                  {r.player.hand === 'L' && <span className="ml-1.5 text-[10px] text-amber-300/80">LH</span>}
                </td>
                <td className="hidden px-3 py-2 text-right font-mono text-zinc-400 sm:table-cell">{r.player.age ?? '—'}</td>
                <td className="px-3 py-2 text-right font-mono text-cyan-400">{num(r.elo, 0)}</td>
                <td className="px-3 py-2 text-right font-mono text-zinc-400">{pct(r.serveSkill)}</td>
                <td className="hidden px-3 py-2 text-right font-mono text-zinc-500 sm:table-cell">{num(r.matches, 0)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </main>
  )
}
