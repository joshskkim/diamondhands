'use client'

import { useQuery } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import { ArrowLeft } from 'lucide-react'
import Link from 'next/link'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api, fetchPlayer } from '@/lib/api'
import type { RecentStat } from '@/lib/types'

function xwobaColor(v: number | null): string {
  if (v == null) return 'text-zinc-400'
  if (v >= 0.4) return 'text-green-600 font-medium'
  if (v >= 0.32) return 'text-zinc-700'
  return 'text-red-500'
}

export function PlayerDetail({ playerId }: { playerId: number }) {
  const { data: player } = useQuery({
    queryKey: ['player', 'detail', playerId],
    queryFn: () => fetchPlayer(playerId),
  })

  const { data: stats, isPending, isError } = useQuery({
    queryKey: ['player', 'recent', playerId],
    queryFn: () => api.recentStats(playerId, 20),
  })

  if (isPending) return <div className="p-8 text-zinc-400">Loading…</div>
  if (isError) return <div className="p-8 text-red-500">Failed to load player stats.</div>

  const chartData = [...(stats ?? [])]
    .reverse()
    .filter((s) => s.xwoba != null)
    .map((s) => ({ date: s.gameDate, xwoba: s.xwoba }))

  return (
    <main className="max-w-4xl mx-auto w-full px-4 py-8">
      <Link href="/" className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-zinc-800 mb-6">
        <ArrowLeft size={14} /> All Games
      </Link>

      <h1 className="text-2xl font-bold mb-1">
        {player ? player.fullName : `Player #${playerId}`}
      </h1>
      {player && (
        <p className="text-sm text-zinc-500 mb-1">
          {[player.teamAbbr, player.position, `B/T: ${player.bats ?? '?'}/${player.throwsHand ?? '?'}`]
            .filter(Boolean)
            .join(' · ')}
        </p>
      )}

      {stats && stats.length === 0 && (
        <p className="text-zinc-500 mt-4">No recent activity.</p>
      )}

      {stats && stats.length > 0 && (
        <>
          {/* xwOBA chart */}
          {chartData.length > 1 && (
            <div className="bg-white border border-zinc-200 rounded-xl p-4 mb-6">
              <p className="text-xs text-zinc-500 mb-3">xwOBA — last {chartData.length} games</p>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#e4e4e7" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10, fill: '#a1a1aa' }}
                    tickFormatter={(d) => format(parseISO(d), 'M/d')}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    domain={[0, 0.8]}
                    tick={{ fontSize: 10, fill: '#a1a1aa' }}
                    tickFormatter={(v) => v.toFixed(2)}
                  />
                  <Tooltip
                    formatter={(v) => [typeof v === 'number' ? v.toFixed(3) : v, 'xwOBA']}
                    labelFormatter={(d) => format(parseISO(d as string), 'MMM d')}
                  />
                  <Line
                    type="monotone"
                    dataKey="xwoba"
                    stroke="#2563eb"
                    strokeWidth={1.5}
                    dot={false}
                    activeDot={{ r: 3 }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* game log table */}
          <div className="bg-white border border-zinc-200 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-zinc-100 text-sm font-semibold">
              Last {stats.length} Games
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className="border-b border-zinc-100 text-xs font-medium text-zinc-500">
                    <th className="px-3 py-2 text-left">Date</th>
                    <th className="px-3 py-2 text-left">Opp</th>
                    <th className="px-3 py-2 text-left">H/A</th>
                    <th className="px-3 py-2 text-right">PA</th>
                    <th className="px-3 py-2 text-right">H</th>
                    <th className="px-3 py-2 text-right">HR</th>
                    <th className="px-3 py-2 text-right">K</th>
                    <th className="px-3 py-2 text-right">xwOBA</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.map((s: RecentStat, i: number) => (
                    <tr
                      key={`${s.gameDate}-${i}`}
                      className="border-b border-zinc-50 hover:bg-zinc-50"
                    >
                      <td className="px-3 py-2 tabular-nums text-zinc-600">
                        {format(parseISO(s.gameDate), 'MMM d')}
                      </td>
                      <td className="px-3 py-2 font-medium">{s.opp ?? '—'}</td>
                      <td className="px-3 py-2 text-zinc-500">{s.isHome ? 'H' : 'A'}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{s.pa}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{s.hits}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{s.hr}</td>
                      <td className="px-3 py-2 text-right tabular-nums">{s.k}</td>
                      <td className={`px-3 py-2 text-right tabular-nums ${xwobaColor(s.xwoba)}`}>
                        {s.xwoba != null ? s.xwoba.toFixed(3) : '—'}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}
    </main>
  )
}
