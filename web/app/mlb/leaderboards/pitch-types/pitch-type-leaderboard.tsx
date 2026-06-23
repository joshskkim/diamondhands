'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import {
  pitchTypeLeaderboardQueryOptions,
  pitchTypesQueryOptions,
} from '@/lib/api'
import { cn } from '@/lib/utils'
import { QueryError } from '@/components/ui/query-states'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

function edgeClass(edge: number) {
  if (edge > 0.02) return 'text-emerald-400'
  if (edge < -0.02) return 'text-rose-400'
  return 'text-zinc-400'
}

export function PitchTypeLeaderboard() {
  const { data: pitchTypes } = useQuery(pitchTypesQueryOptions())
  const [pitch, setPitch] = useState<string | null>(null)
  const active = pitch ?? pitchTypes?.[0]?.code ?? null

  const { data: rows, isPending, isError, refetch } = useQuery({
    ...pitchTypeLeaderboardQueryOptions(active ?? '', undefined, 20),
    enabled: Boolean(active),
  })

  return (
    <main className="max-w-5xl mx-auto px-4 py-8">
      <div className={microLabel}>Leaderboard</div>
      <h1 className="text-2xl font-bold tracking-tight text-zinc-100 mt-1 mb-2">
        Pitch Matchups
      </h1>
      <p className="text-sm text-zinc-400 mb-5 max-w-2xl">
        Today&apos;s hitters with the biggest <span className="text-zinc-200">edge</span> against a
        pitch their opposing starter throws often. <span className="text-zinc-200">Edge</span> = the
        batter&apos;s regressed xwOBA on that pitch minus the league baseline — positive means the
        hitter handles it better than average. Regressed to league by sample size.
      </p>

      {/* segmented control */}
      <div className="flex flex-wrap gap-2 mb-6">
        {pitchTypes?.map((pt) => (
          <button
            key={pt.code}
            onClick={() => setPitch(pt.code)}
            className={cn(
              'text-xs px-3 py-1.5 rounded border transition-colors',
              pt.code === active
                ? 'bg-cyan-500 text-zinc-950 border-cyan-500 font-medium'
                : 'bg-white/5 text-zinc-300 border-white/10 hover:border-cyan-400/40 hover:text-zinc-100',
            )}
          >
            {pt.name}
          </button>
        ))}
      </div>

      {isPending && active ? (
        <div className="space-y-2">
          {Array.from({ length: 8 }).map((_, i) => (
            <div key={i} className="h-9 animate-pulse bg-white/5 rounded" />
          ))}
        </div>
      ) : isError ? (
        <QueryError message="Couldn’t load the leaderboard." onRetry={refetch} />
      ) : !rows || rows.length === 0 ? (
        <div className="p-6 text-zinc-500 text-sm bg-[#0e1015] border border-white/10 rounded-xl">
          No qualifying batters today against this pitch type.
        </div>
      ) : (
        <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden">
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className={cn('border-b border-white/10', microLabel)}>
                  <th className="px-3 py-2 text-left font-medium">Batter</th>
                  <th className="px-3 py-2 text-left font-medium">vs Pitcher</th>
                  <th className="px-3 py-2 text-right font-medium">Uses</th>
                  <th className="px-3 py-2 text-right font-medium">Batter xwOBA</th>
                  <th className="px-3 py-2 text-right font-medium">League</th>
                  <th className="px-3 py-2 text-right font-medium">Edge</th>
                  <th className="px-3 py-2 text-right font-medium">Pitches</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((r) => (
                  <tr
                    key={`${r.player.id}-${r.opposingPitcher.id}`}
                    className="border-b border-white/5 hover:bg-white/[0.03] transition-colors"
                  >
                    <td className="px-3 py-2">
                      <Link
                        href={`/mlb/players/${r.player.id}`}
                        className="font-medium text-zinc-100 hover:text-cyan-400 transition-colors"
                      >
                        {r.player.name}
                      </Link>
                      <span className="text-zinc-500 text-xs ml-1.5">{r.player.teamAbbr}</span>
                    </td>
                    <td className="px-3 py-2 text-zinc-400">
                      {r.opposingPitcher.name}
                      <span className="text-zinc-600 text-xs ml-1">
                        ({r.opposingPitcher.throws})
                      </span>
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">
                      {(r.pitchTypeUsage * 100).toFixed(0)}%
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-200">
                      {r.batterXwoba.toFixed(3)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-500">
                      {r.leagueXwoba.toFixed(3)}
                    </td>
                    <td className={cn('px-3 py-2 text-right font-mono tabular-nums font-medium', edgeClass(r.edge))}>
                      {r.edge >= 0 ? '+' : ''}
                      {r.edge.toFixed(3)}
                    </td>
                    <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-500">
                      {r.pitchesSeen}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </main>
  )
}
