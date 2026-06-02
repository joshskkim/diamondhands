'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import {
  pitchTypeLeaderboardQueryOptions,
  pitchTypesQueryOptions,
} from '@/lib/api'

function cn(...parts: Array<string | false | null | undefined>) {
  return parts.filter(Boolean).join(' ')
}

function edgeClass(edge: number) {
  if (edge > 0.02) return 'text-green-600'
  if (edge < -0.02) return 'text-red-500'
  return 'text-zinc-500'
}

export function PitchTypeLeaderboard() {
  const { data: pitchTypes } = useQuery(pitchTypesQueryOptions())
  const [pitch, setPitch] = useState<string | null>(null)
  const active = pitch ?? pitchTypes?.[0]?.code ?? null

  const { data: rows, isPending, isError } = useQuery({
    ...pitchTypeLeaderboardQueryOptions(active ?? '', undefined, 20),
    enabled: Boolean(active),
  })

  return (
    <main className="max-w-5xl mx-auto px-4 py-8">
      <h1 className="text-2xl font-bold tracking-tight mb-1">Pitch-Type Matchups</h1>
      <p className="text-sm text-zinc-500 mb-5">
        Today&apos;s hitters with the biggest xwOBA edge against a pitch their opposing
        starter throws often. Regressed to league by sample size.
      </p>

      <div className="flex flex-wrap gap-2 mb-6">
        {pitchTypes?.map((pt) => (
          <button
            key={pt.code}
            onClick={() => setPitch(pt.code)}
            className={cn(
              'text-xs px-3 py-1.5 rounded border transition-colors',
              pt.code === active
                ? 'bg-zinc-900 text-white border-zinc-900'
                : 'bg-white text-zinc-600 border-zinc-300 hover:border-zinc-500',
            )}
          >
            {pt.name}
          </button>
        ))}
      </div>

      {isPending && active ? (
        <div className="p-8 text-zinc-400">Loading leaderboard…</div>
      ) : isError ? (
        <div className="p-8 text-red-500">Failed to load leaderboard.</div>
      ) : !rows || rows.length === 0 ? (
        <div className="p-8 text-zinc-400">
          No qualifying batters today against this pitch type.
        </div>
      ) : (
        <div className="bg-white border border-zinc-200 rounded-xl overflow-hidden">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-b border-zinc-200 text-xs font-medium text-zinc-500">
                <th className="px-3 py-2 text-left">Batter</th>
                <th className="px-3 py-2 text-left">vs Pitcher</th>
                <th className="px-3 py-2 text-right">Uses</th>
                <th className="px-3 py-2 text-right">Batter xwOBA</th>
                <th className="px-3 py-2 text-right">League</th>
                <th className="px-3 py-2 text-right">Edge</th>
                <th className="px-3 py-2 text-right">Pitches</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr
                  key={`${r.player.id}-${r.opposingPitcher.id}`}
                  className="border-b border-zinc-100 hover:bg-zinc-50"
                >
                  <td className="px-3 py-2">
                    <Link
                      href={`/players/${r.player.id}`}
                      className="font-medium text-zinc-900 hover:text-blue-600"
                    >
                      {r.player.name}
                    </Link>
                    <span className="text-zinc-400 text-xs ml-1">{r.player.teamAbbr}</span>
                  </td>
                  <td className="px-3 py-2 text-zinc-600">
                    {r.opposingPitcher.name}
                    <span className="text-zinc-400 text-xs ml-1">
                      ({r.opposingPitcher.throws})
                    </span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {(r.pitchTypeUsage * 100).toFixed(0)}%
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums">
                    {r.batterXwoba.toFixed(3)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-zinc-400">
                    {r.leagueXwoba.toFixed(3)}
                  </td>
                  <td className={cn('px-3 py-2 text-right tabular-nums font-medium', edgeClass(r.edge))}>
                    {r.edge >= 0 ? '+' : ''}
                    {r.edge.toFixed(3)}
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-zinc-400">
                    {r.pitchesSeen}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </main>
  )
}
