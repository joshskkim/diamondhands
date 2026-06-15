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
import { api, fetchPlayer, playerSprayQueryOptions } from '@/lib/api'
import type { RecentStat } from '@/lib/types'
import { cn } from '@/lib/utils'
import { getStadiumByAbbr } from '@/lib/stadiums'
import { StadiumDiagram } from '@/components/game/stadium-diagram'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'
const chip =
  'inline-flex items-center gap-1 text-[11px] rounded px-1.5 py-0.5 bg-white/5 border border-white/10 text-zinc-300'

function xwobaColor(v: number | null): string {
  if (v == null) return 'text-zinc-500'
  if (v >= 0.4) return 'text-emerald-400 font-medium'
  if (v >= 0.32) return 'text-zinc-300'
  return 'text-rose-400'
}

function StatTile({
  label,
  value,
  valueClass,
}: {
  label: string
  value: string
  valueClass?: string
}) {
  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl px-4 py-3">
      <div className={microLabel}>{label}</div>
      <div className={cn('mt-1 text-xl font-semibold font-mono tabular-nums text-zinc-100', valueClass)}>
        {value}
      </div>
    </div>
  )
}

function SummaryStrip({ stats }: { stats: RecentStat[] }) {
  const pa = stats.reduce((s, g) => s + g.pa, 0)
  const h = stats.reduce((s, g) => s + g.hits, 0)
  const hr = stats.reduce((s, g) => s + g.hr, 0)
  const k = stats.reduce((s, g) => s + g.k, 0)
  const xw = stats.filter((g) => g.xwoba != null) as Array<RecentStat & { xwoba: number }>
  const avgXwoba = xw.length > 0 ? xw.reduce((s, g) => s + g.xwoba, 0) / xw.length : null

  return (
    <div className="grid grid-cols-3 sm:grid-cols-5 gap-3 mb-6">
      <StatTile label={`PA · last ${stats.length}`} value={String(pa)} />
      <StatTile label="Hits" value={String(h)} />
      <StatTile label="HR" value={String(hr)} />
      <StatTile label="K" value={String(k)} />
      <StatTile
        label="Avg xwOBA"
        value={avgXwoba != null ? avgXwoba.toFixed(3) : '—'}
        valueClass={xwobaColor(avgXwoba)}
      />
    </div>
  )
}

function HeaderSkeleton() {
  return (
    <div className="mb-6 space-y-2">
      <div className="h-7 w-56 animate-pulse bg-white/5 rounded" />
      <div className="h-4 w-72 animate-pulse bg-white/5 rounded" />
    </div>
  )
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

  const { data: spray } = useQuery(playerSprayQueryOptions(playerId))
  // The spray bins are park-independent; the player's home park just gives the
  // wedges a familiar fence to land against.
  const homePark = getStadiumByAbbr(player?.teamAbbr)

  const chartData = [...(stats ?? [])]
    .reverse()
    .filter((s) => s.xwoba != null)
    .map((s) => ({ date: s.gameDate, xwoba: s.xwoba }))

  return (
    <main className="max-w-4xl mx-auto w-full px-4 py-8">
      <Link
        href="/"
        className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-cyan-400 transition-colors mb-6"
      >
        <ArrowLeft size={14} /> Today&apos;s Board
      </Link>

      {/* header */}
      {player ? (
        <div className="mb-6">
          <h1 className="text-2xl font-bold tracking-tight text-zinc-100 mb-2">
            {player.fullName}
          </h1>
          <div className="flex flex-wrap gap-2">
            {player.teamAbbr && <span className={chip}>{player.teamAbbr}</span>}
            {player.position && <span className={chip}>{player.position}</span>}
            <span className={chip}>
              <span className={microLabel}>Bats</span>
              <span className="text-zinc-200">{player.bats ?? '?'}</span>
              <span className="text-zinc-600">·</span>
              <span className={microLabel}>Throws</span>
              <span className="text-zinc-200">{player.throwsHand ?? '?'}</span>
            </span>
          </div>
        </div>
      ) : (
        <HeaderSkeleton />
      )}

      {isPending && (
        <div className="space-y-3">
          <div className="grid grid-cols-3 sm:grid-cols-5 gap-3">
            {Array.from({ length: 5 }).map((_, i) => (
              <div key={i} className="h-16 animate-pulse bg-white/5 rounded-xl" />
            ))}
          </div>
          <div className="h-48 animate-pulse bg-white/5 rounded-xl" />
        </div>
      )}
      {isError && <p className="text-rose-400">Failed to load player stats.</p>}

      {stats && stats.length === 0 && (
        <p className="text-zinc-500 mt-4">No recent activity.</p>
      )}

      {stats && stats.length > 0 && (
        <>
          <SummaryStrip stats={stats} />

          {/* xwOBA chart */}
          {chartData.length > 1 && (
            <div className="bg-[#0e1015] border border-white/10 rounded-xl p-4 mb-6">
              <p className={cn(microLabel, 'mb-3')}>
                xwOBA — last {chartData.length} games
              </p>
              <ResponsiveContainer width="100%" height={180}>
                <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#27272a" />
                  <XAxis
                    dataKey="date"
                    tick={{ fontSize: 10, fill: '#71717a' }}
                    tickFormatter={(d) => format(parseISO(d), 'M/d')}
                    interval="preserveStartEnd"
                  />
                  <YAxis
                    domain={[0, 0.8]}
                    tick={{ fontSize: 10, fill: '#71717a' }}
                    tickFormatter={(v) => v.toFixed(2)}
                  />
                  <Tooltip
                    contentStyle={{
                      background: '#0e1015',
                      border: '1px solid rgba(255,255,255,0.1)',
                      borderRadius: 8,
                      color: '#e4e4e7',
                      fontSize: 12,
                    }}
                    labelStyle={{ color: '#a1a1aa' }}
                    formatter={(v) => [typeof v === 'number' ? v.toFixed(3) : v, 'xwOBA']}
                    labelFormatter={(d) => format(parseISO(d as string), 'MMM d')}
                  />
                  <Line
                    type="monotone"
                    dataKey="xwoba"
                    stroke="#22d3ee"
                    strokeWidth={1.5}
                    dot={false}
                    activeDot={{ r: 3, fill: '#22d3ee' }}
                  />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}

          {/* spray chart over the player's home park */}
          {spray && spray.totalBip > 0 && (
            <div className="mb-6">
              <StadiumDiagram
                stadium={homePark}
                stadiumName={homePark?.stadiumName ?? 'Spray chart'}
                isDome={homePark?.isDome ?? false}
                weather={{ tempF: null, windMph: null, windDirDeg: null }}
                spray={spray}
                sprayLabel={player?.fullName}
              />
            </div>
          )}

          {/* game log table */}
          <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden">
            <div className="px-4 py-3 border-b border-white/10 text-sm font-semibold tracking-tight text-zinc-100">
              Last {stats.length} Games
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead>
                  <tr className={cn('border-b border-white/10', microLabel)}>
                    <th className="px-3 py-2 text-left font-medium max-md:sticky max-md:left-0 max-md:z-10 max-md:bg-[#0e1015]">Date</th>
                    <th className="px-3 py-2 text-left font-medium">Opp</th>
                    <th className="px-3 py-2 text-left font-medium">H/A</th>
                    <th className="px-3 py-2 text-right font-medium">PA</th>
                    <th className="px-3 py-2 text-right font-medium">H</th>
                    <th className="px-3 py-2 text-right font-medium">HR</th>
                    <th className="px-3 py-2 text-right font-medium">K</th>
                    <th className="px-3 py-2 text-right font-medium">xwOBA</th>
                  </tr>
                </thead>
                <tbody>
                  {stats.map((s: RecentStat, i: number) => (
                    <tr
                      key={`${s.gameDate}-${i}`}
                      className="border-b border-white/5 hover:bg-white/[0.03] transition-colors"
                    >
                      <td className="px-3 py-2 font-mono tabular-nums text-zinc-400 max-md:sticky max-md:left-0 max-md:z-10 max-md:bg-[#0e1015]">
                        {format(parseISO(s.gameDate), 'MMM d')}
                      </td>
                      <td className="px-3 py-2 font-medium text-zinc-200">{s.opp ?? '—'}</td>
                      <td className="px-3 py-2 text-zinc-500">{s.isHome ? 'H' : 'A'}</td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">{s.pa}</td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">{s.hits}</td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">{s.hr}</td>
                      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">{s.k}</td>
                      <td className={cn('px-3 py-2 text-right font-mono tabular-nums', xwobaColor(s.xwoba))}>
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
