'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import {
  CartesianGrid,
  Line,
  LineChart,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { trackRecordQueryOptions } from '@/lib/api'
import type { RecordSummary, TrackRecord } from '@/lib/types'
import { cn } from '@/lib/utils'
import { QueryError } from '@/components/ui/query-states'
import { AccuracyBoard } from '../accuracy/accuracy-board'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

// Below this many settled picks, units/ROI swing wildly on a single result — show the
// caveat and let the steadier calibration section carry the "is the model good" story.
const MIN_MEANINGFUL_N = 50

// All-time uses a large day count; the API clamps and the equity curve just spans everything.
const ALL_DAYS = 36500
const WINDOWS = [
  { label: '14d', days: 14 },
  { label: '30d', days: 30 },
  { label: '60d', days: 60 },
  { label: 'All', days: ALL_DAYS },
] as const

const MARKET_LABEL: Record<string, string> = {
  total: 'Totals',
  moneyline: 'Moneyline',
  run_line: 'Run Line',
  hr: 'Home Run',
  hit: 'Hits',
}

function signedUnits(u: number): string {
  return `${u >= 0 ? '+' : ''}${u.toFixed(2)}u`
}

function unitsClass(u: number): string {
  if (u > 0.001) return 'text-emerald-400'
  if (u < -0.001) return 'text-rose-400'
  return 'text-zinc-300'
}

function fmtDate(iso: string) {
  return format(parseISO(iso), 'MMM d')
}

// One version → "model vX"; a span → "models vMin–vMax (n)". Full list is in the title tooltip.
function modelVersionLabel(versions: string[]): string {
  if (versions.length === 1) return `model ${versions[0]}`
  return `models ${versions[0]}–${versions[versions.length - 1]} (${versions.length})`
}

export function ReportCard() {
  const [days, setDays] = useState<number>(60)
  const { data, isPending, isError, refetch } = useQuery(trackRecordQueryOptions(days))

  return (
    <main className="max-w-5xl mx-auto px-4 py-8">
      <div className={microLabel}>Model</div>
      <h1 className="text-2xl font-bold tracking-tight text-zinc-100 mt-1 mb-2">Report Card</h1>
      <p className="text-sm text-zinc-400 mb-5 max-w-2xl">
        The live track record of the published <span className="text-zinc-200">Model&apos;s Picks</span>{' '}
        — graded the morning after each slate. Records assume a flat 1-unit stake at the price we
        recorded. This is how the actual <em>picks</em> did; the model&apos;s overall calibration
        (every projection, not just the bets) is below.
      </p>

      <div className="flex items-center justify-between mb-5">
        <div className="flex gap-1.5">
          {WINDOWS.map((w) => (
            <button
              key={w.label}
              type="button"
              onClick={() => setDays(w.days)}
              className={cn(
                'px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
                days === w.days
                  ? 'bg-cyan-400/15 text-cyan-300 ring-1 ring-cyan-400/30'
                  : 'text-zinc-400 hover:text-zinc-100 hover:bg-white/5',
              )}
            >
              {w.label}
            </button>
          ))}
        </div>
        <div className="flex items-center gap-3 text-xs text-zinc-500 font-mono">
          {data && data.modelVersions.length > 0 && (
            <span title={data.modelVersions.join(', ')}>{modelVersionLabel(data.modelVersions)}</span>
          )}
          {data?.asOf && <span>through {fmtDate(data.asOf)}</span>}
        </div>
      </div>

      {isPending && <div className="text-sm text-zinc-500">Loading track record…</div>}
      {isError && <QueryError message="Couldn’t load the track record." onRetry={refetch} />}
      {!isPending && !isError && data && data.overall.n === 0 && (
        <div className="text-sm text-zinc-500">
          No graded picks in this window yet. The record fills in as{' '}
          <code className="text-zinc-400">record-picks</code> /{' '}
          <code className="text-zinc-400">score-picks</code> run each night.
        </div>
      )}

      {data && data.overall.n > 0 && data.overall.n < MIN_MEANINGFUL_N && (
        <div className="mb-4 rounded-lg border border-amber-400/20 bg-amber-400/[0.06] px-4 py-2.5 text-xs text-amber-200/90">
          Early sample — {data.overall.n} graded pick{data.overall.n === 1 ? '' : 's'}. Units and ROI
          swing hard on a single result here and aren&apos;t yet statistically meaningful; the
          projection calibration below is the steadier read on model quality.
        </div>
      )}

      {data && data.overall.n > 0 && (
        <>
          <SummaryRow tr={data} />
          <EquityCurve tr={data} />
          <div className="grid gap-4 sm:grid-cols-2 mt-6">
            <BreakdownTable title="By market" rows={data.byMarket} labelOf={(l) => MARKET_LABEL[l] ?? l} />
            <BreakdownTable title="By conviction" rows={data.byTier} labelOf={(l) => l} />
          </div>
        </>
      )}

      {/* Section B — projection calibration (every projection, the unbiased model read). */}
      <AccuracyBoard />
    </main>
  )
}

function SummaryRow({ tr }: { tr: TrackRecord }) {
  const o = tr.overall
  const record = `${o.wins}-${o.losses}${o.pushes ? `-${o.pushes}` : ''}`
  return (
    <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
      <StatCard label="Record" value={record} sub={`${o.n} settled`} />
      <StatCard label="Win %" value={`${(o.winPct * 100).toFixed(1)}%`} sub="of decided picks" />
      <StatCard
        label="Units"
        value={signedUnits(o.units)}
        valueClass={unitsClass(o.units)}
        sub="flat 1u stakes"
      />
      <StatCard
        label="ROI"
        value={`${o.roiPct >= 0 ? '+' : ''}${o.roiPct.toFixed(1)}%`}
        valueClass={unitsClass(o.roiPct)}
        sub={tr.pickBrier != null ? `pick Brier ${tr.pickBrier.toFixed(3)}` : undefined}
      />
    </div>
  )
}

function StatCard({
  label,
  value,
  sub,
  valueClass,
}: {
  label: string
  value: string
  sub?: string
  valueClass?: string
}) {
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
      <div className={microLabel}>{label}</div>
      <div className={cn('text-2xl font-mono font-semibold mt-1', valueClass ?? 'text-zinc-100')}>
        {value}
      </div>
      {sub && <div className="text-[11px] text-zinc-500 mt-0.5">{sub}</div>}
    </div>
  )
}

function EquityCurve({ tr }: { tr: TrackRecord }) {
  const chartData = tr.equity.map((p) => ({ date: fmtDate(p.date), units: p.cumUnits }))
  if (chartData.length < 2) {
    return (
      <p className="text-xs text-zinc-600 mt-4">
        Equity curve appears once there are at least two graded slates.
      </p>
    )
  }
  return (
    <div className="mt-6 rounded-xl border border-white/10 bg-white/[0.02] p-4">
      <div className={cn(microLabel, 'mb-1')}>Cumulative units</div>
      <ResponsiveContainer width="100%" height={200}>
        <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
          <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#a1a1aa' }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 10, fill: '#a1a1aa' }} domain={['auto', 'auto']} width={44} />
          <ReferenceLine y={0} stroke="#52525b" strokeDasharray="4 4" />
          <Tooltip
            contentStyle={{
              background: '#15171c',
              border: '1px solid #ffffff20',
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: '#e4e4e7' }}
            formatter={(value) => [signedUnits(Number(value)), 'units'] as [string, string]}
          />
          <Line type="monotone" dataKey="units" stroke="#22d3ee" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function BreakdownTable({
  title,
  rows,
  labelOf,
}: {
  title: string
  rows: RecordSummary[]
  labelOf: (label: string) => string
}) {
  if (rows.length === 0) return null
  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
      <div className={cn(microLabel, 'mb-2')}>{title}</div>
      <table className="w-full text-sm">
        <thead>
          <tr className="text-[11px] uppercase tracking-wide text-zinc-500">
            <th className="text-left font-medium pb-1.5"></th>
            <th className="text-right font-medium pb-1.5">Record</th>
            <th className="text-right font-medium pb-1.5">Units</th>
            <th className="text-right font-medium pb-1.5">ROI</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => (
            <tr key={r.label} className="border-t border-white/5">
              <td className="py-1.5 text-zinc-200">{labelOf(r.label)}</td>
              <td className="py-1.5 text-right font-mono text-zinc-300">
                {r.wins}-{r.losses}
                {r.pushes ? `-${r.pushes}` : ''}
              </td>
              <td className={cn('py-1.5 text-right font-mono', unitsClass(r.units))}>
                {signedUnits(r.units)}
              </td>
              <td className={cn('py-1.5 text-right font-mono', unitsClass(r.roiPct))}>
                {r.roiPct >= 0 ? '+' : ''}
                {r.roiPct.toFixed(1)}%
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
