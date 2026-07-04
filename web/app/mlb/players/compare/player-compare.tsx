'use client'

import { useCallback } from 'react'
import Link from 'next/link'
import { useRouter, useSearchParams } from 'next/navigation'
import { useQueries } from '@tanstack/react-query'
import { Users, X, ArrowLeft } from 'lucide-react'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { fetchPlayer, fetchPlayerRecentStats, queryKeys } from '@/lib/api'
import type { PlayerDetail, RecentStat } from '@/lib/types'
import { cn } from '@/lib/utils'
import { PlayerSearch } from '@/components/player-search'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

// Up to three keeps columns readable and the trend lines visually distinct.
const MAX_PLAYERS = 3
const RECENT_N = 20

// One accent per column, reused by the header, the table, and the chart lines.
const ACCENTS = ['#22d3ee', '#f59e0b', '#a78bfa'] as const

interface Agg {
  games: number
  pa: number
  hits: number
  hr: number
  k: number
  /** Mean of per-game xwOBA over games where it was recorded. */
  xwoba: number | null
}

function aggregate(stats: RecentStat[]): Agg {
  const xw = stats.filter((s) => s.xwoba != null) as Array<RecentStat & { xwoba: number }>
  return {
    games: stats.length,
    pa: stats.reduce((s, g) => s + g.pa, 0),
    hits: stats.reduce((s, g) => s + g.hits, 0),
    hr: stats.reduce((s, g) => s + g.hr, 0),
    k: stats.reduce((s, g) => s + g.k, 0),
    xwoba: xw.length > 0 ? xw.reduce((s, g) => s + g.xwoba, 0) / xw.length : null,
  }
}

type Compare = 'high' | 'low' | null

interface Metric {
  label: string
  /** null when undefined (e.g. no PA → no rate). */
  value: (a: Agg) => number | null
  fmt: (v: number) => string
  compare: Compare
  /** Visually separates the counting block from the rate block. */
  groupStart?: boolean
}

const int = (v: number) => String(Math.round(v))
const rate3 = (v: number) => v.toFixed(3)
const perPA = (n: number, pa: number) => (pa > 0 ? n / pa : null)

const METRICS: Metric[] = [
  { label: 'Games', value: (a) => a.games, fmt: int, compare: null },
  { label: 'PA', value: (a) => a.pa, fmt: int, compare: null },
  { label: 'Hits', value: (a) => a.hits, fmt: int, compare: 'high' },
  { label: 'HR', value: (a) => a.hr, fmt: int, compare: 'high' },
  { label: 'K', value: (a) => a.k, fmt: int, compare: 'low' },
  { label: 'H / PA', value: (a) => perPA(a.hits, a.pa), fmt: rate3, compare: 'high', groupStart: true },
  { label: 'HR / PA', value: (a) => perPA(a.hr, a.pa), fmt: rate3, compare: 'high' },
  { label: 'K / PA', value: (a) => perPA(a.k, a.pa), fmt: rate3, compare: 'low' },
  { label: 'Avg xwOBA', value: (a) => a.xwoba, fmt: rate3, compare: 'high' },
]

// Index of the column(s) holding the best value for a metric, for emerald emphasis.
// Ties highlight all leaders; a single populated column is never "best" (nothing to beat).
function bestColumns(values: (number | null)[], compare: Compare): Set<number> {
  if (!compare) return new Set()
  const present = values.filter((v): v is number => v != null)
  if (present.length < 2) return new Set()
  const target = compare === 'high' ? Math.max(...present) : Math.min(...present)
  const out = new Set<number>()
  values.forEach((v, i) => {
    if (v != null && v === target) out.add(i)
  })
  return out
}

function parseIds(raw: string | null): number[] {
  if (!raw) return []
  const seen = new Set<number>()
  const ids: number[] = []
  for (const part of raw.split(',')) {
    const n = Number(part.trim())
    if (Number.isInteger(n) && n > 0 && !seen.has(n)) {
      seen.add(n)
      ids.push(n)
      if (ids.length === MAX_PLAYERS) break
    }
  }
  return ids
}

export function PlayerCompare() {
  const router = useRouter()
  const params = useSearchParams()
  const ids = parseIds(params.get('ids'))

  // Persist the roster in the URL so a comparison is shareable and back/forward works.
  const setIds = useCallback(
    (next: number[]) => {
      const qs = next.length > 0 ? `?ids=${next.join(',')}` : ''
      router.replace(`/mlb/players/compare${qs}`, { scroll: false })
    },
    [router],
  )

  const addPlayer = (p: PlayerDetail) => {
    if (ids.includes(p.id) || ids.length >= MAX_PLAYERS) return
    setIds([...ids, p.id])
  }
  const removePlayer = (id: number) => setIds(ids.filter((x) => x !== id))

  const details = useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.players.detail(id),
      queryFn: () => fetchPlayer(id),
    })),
  })
  const recents = useQueries({
    queries: ids.map((id) => ({
      queryKey: queryKeys.players.recent(id, RECENT_N),
      queryFn: () => fetchPlayerRecentStats(id, RECENT_N),
    })),
  })

  const columns = ids.map((id, i) => ({
    id,
    accent: ACCENTS[i],
    player: details[i]?.data,
    stats: recents[i]?.data ?? [],
    loading: details[i]?.isPending || recents[i]?.isPending,
  }))
  const aggs = columns.map((c) => aggregate(c.stats))

  return (
    <main className="mx-auto w-full max-w-5xl px-4 py-8">
      <Link
        href="/"
        className="mb-6 inline-flex items-center gap-1 text-sm text-zinc-500 transition-colors hover:text-cyan-400"
      >
        <ArrowLeft size={14} /> Today&apos;s Board
      </Link>

      <div className="mb-1 flex items-center gap-2">
        <Users className="h-5 w-5 text-cyan-300" aria-hidden="true" />
        <h1 className="text-2xl font-bold tracking-tight text-zinc-100">Compare Players</h1>
      </div>
      <p className="mb-6 max-w-2xl text-sm text-zinc-400">
        Stack up to {MAX_PLAYERS} batters on their last {RECENT_N} games — counting stats, per-PA
        rates, and the xwOBA trend. The best value in each comparative row is highlighted.
      </p>

      {ids.length === 0 ? (
        <EmptyState onAdd={addPlayer} />
      ) : (
        <>
          {/* roster header — one card per player + an add slot */}
          <div className="mb-5 grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
            {columns.map((c) => (
              <PlayerHeaderCard
                key={c.id}
                accent={c.accent}
                player={c.player}
                onRemove={() => removePlayer(c.id)}
              />
            ))}
            {ids.length < MAX_PLAYERS && (
              <div className="rounded-xl border border-dashed border-white/15 bg-white/[0.02] p-3">
                <p className={cn(microLabel, 'mb-2')}>Add a player</p>
                <PlayerSearch
                  placeholder="Search to add…"
                  onSelect={addPlayer}
                  excludeIds={ids}
                  clearOnSelect
                />
              </div>
            )}
          </div>

          <StatTable columns={columns} aggs={aggs} />
          <TrendChart columns={columns} />
        </>
      )}
    </main>
  )
}

function EmptyState({ onAdd }: { onAdd: (p: PlayerDetail) => void }) {
  return (
    <div className="rounded-2xl border border-white/10 bg-white/[0.02] px-6 py-12 text-center">
      <Users className="mx-auto mb-3 h-8 w-8 text-zinc-600" aria-hidden="true" />
      <h2 className="text-base font-semibold text-zinc-100">Pick two or more batters</h2>
      <p className="mx-auto mt-1.5 mb-5 max-w-md text-sm text-zinc-400">
        Search for a player to start a comparison. Add up to {MAX_PLAYERS} and they line up
        side by side. The roster lives in the URL, so a comparison is shareable.
      </p>
      <div className="mx-auto max-w-sm">
        <PlayerSearch placeholder="Search players…" autoFocus onSelect={onAdd} clearOnSelect />
      </div>
    </div>
  )
}

function PlayerHeaderCard({
  accent,
  player,
  onRemove,
}: {
  accent: string
  player: PlayerDetail | undefined
  onRemove: () => void
}) {
  return (
    <div className="relative rounded-xl border border-white/10 bg-[#0e1015] p-3">
      <span
        className="absolute left-0 top-3 h-[calc(100%-1.5rem)] w-1 rounded-full"
        style={{ background: accent }}
        aria-hidden
      />
      <div className="flex items-start justify-between gap-2 pl-2.5">
        <div className="min-w-0">
          {player ? (
            <Link
              href={`/mlb/players/${player.id}`}
              className="block truncate text-sm font-semibold text-zinc-100 transition-colors hover:text-cyan-300"
            >
              {player.fullName}
            </Link>
          ) : (
            <div className="h-4 w-28 animate-pulse rounded bg-white/10" />
          )}
          <div className="mt-1 font-mono text-xs text-zinc-500">
            {player ? [player.teamAbbr, player.position].filter(Boolean).join(' · ') || '—' : '…'}
          </div>
        </div>
        <button
          type="button"
          onClick={onRemove}
          aria-label="Remove player"
          className="shrink-0 rounded-md p-1 text-zinc-500 transition-colors hover:bg-white/5 hover:text-zinc-200"
        >
          <X className="h-4 w-4" />
        </button>
      </div>
    </div>
  )
}

interface Column {
  id: number
  accent: string
  player: PlayerDetail | undefined
  stats: RecentStat[]
  loading: boolean
}

function StatTable({ columns, aggs }: { columns: Column[]; aggs: Agg[] }) {
  const anyLoading = columns.some((c) => c.loading)
  return (
    <div className="overflow-hidden rounded-xl border border-white/10 bg-[#0e1015]">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/10">
            <th className={cn('px-4 py-2.5 text-left font-medium', microLabel)}>Metric</th>
            {columns.map((c) => (
              <th key={c.id} className="px-4 py-2.5 text-right">
                <span className="font-semibold text-zinc-200" style={{ color: c.accent }}>
                  {c.player ? lastName(c.player.fullName) : '…'}
                </span>
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {METRICS.map((m) => {
            const vals = aggs.map((a) => m.value(a))
            const best = bestColumns(vals, m.compare)
            return (
              <tr
                key={m.label}
                className={cn(
                  'border-b border-white/5 last:border-0',
                  m.groupStart && 'border-t-2 border-t-white/10',
                )}
              >
                <td className="px-4 py-2 text-zinc-400">{m.label}</td>
                {vals.map((v, i) => (
                  <td
                    key={columns[i].id}
                    className={cn(
                      'px-4 py-2 text-right font-mono tabular-nums',
                      best.has(i) ? 'font-semibold text-emerald-400' : 'text-zinc-300',
                    )}
                  >
                    {v == null ? (anyLoading ? '·' : '—') : m.fmt(v)}
                  </td>
                ))}
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

function lastName(full: string): string {
  const parts = full.trim().split(/\s+/)
  return parts.length > 1 ? parts.slice(1).join(' ') : full
}

// Aligns each player's xwOBA series at "now" (rightmost) so recent form lines up,
// regardless of differing game counts or off-days.
function TrendChart({ columns }: { columns: Column[] }) {
  const series = columns.map((c) => {
    // Oldest→newest; player-detail returns newest first, so reverse.
    const xs = [...c.stats].reverse().map((s) => s.xwoba)
    return { id: c.id, accent: c.accent, name: c.player ? lastName(c.player.fullName) : '', xs }
  })
  const maxLen = Math.max(0, ...series.map((s) => s.xs.length))
  if (maxLen < 2) {
    return (
      <p className="mt-4 text-xs text-zinc-600">
        The xwOBA trend appears once a player has at least two recorded games.
      </p>
    )
  }

  // Right-align: index 0 = oldest plotted point, maxLen-1 = most recent.
  const data = Array.from({ length: maxLen }, (_, i) => {
    const row: Record<string, number | null | string> = { pos: i - (maxLen - 1) }
    for (const s of series) {
      const offsetFromEnd = maxLen - 1 - i
      const idx = s.xs.length - 1 - offsetFromEnd
      row[`p${s.id}`] = idx >= 0 ? s.xs[idx] : null
    }
    return row
  })

  return (
    <div className="mt-6 rounded-xl border border-white/10 bg-[#0e1015] p-4">
      <div className={cn(microLabel, 'mb-3')}>xwOBA — recent form (aligned at most recent game)</div>
      <ResponsiveContainer width="100%" height={220}>
        <LineChart data={data} margin={{ top: 4, right: 8, bottom: 0, left: -16 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
          <XAxis
            dataKey="pos"
            tick={{ fontSize: 10, fill: '#71717a' }}
            tickFormatter={(v: number) => (v === 0 ? 'now' : String(v))}
          />
          <YAxis
            domain={[0, 0.8]}
            tick={{ fontSize: 10, fill: '#71717a' }}
            tickFormatter={(v: number) => v.toFixed(2)}
          />
          <Tooltip
            contentStyle={{
              background: '#0e1015',
              border: '1px solid rgba(255,255,255,0.1)',
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: '#a1a1aa' }}
            labelFormatter={(v) => (Number(v) === 0 ? 'Most recent' : `${Math.abs(Number(v))} games ago`)}
            formatter={(value, name) => [
              typeof value === 'number' ? value.toFixed(3) : '—',
              String(name),
            ]}
          />
          {series.map((s) => (
            <Line
              key={s.id}
              type="monotone"
              dataKey={`p${s.id}`}
              name={s.name}
              stroke={s.accent}
              strokeWidth={1.75}
              dot={false}
              connectNulls
              activeDot={{ r: 3, fill: s.accent }}
            />
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
