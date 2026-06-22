'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { format, parseISO } from 'date-fns'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { accuracyQueryOptions } from '@/lib/api'
import type { MarketAccuracy } from '@/lib/types'
import { cn } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

const MARKET_LABEL: Record<string, string> = {
  hit1plus: 'Hit ≥ 1',
  hit2plus: 'Hit ≥ 2',
  hr: 'Home Run',
  k1plus: 'Strikeout ≥ 1',
  total_runs: 'Total Runs',
}

const WINDOWS = [14, 30, 60, 90] as const

function fmtDate(iso: string) {
  return format(parseISO(iso), 'MMM d')
}

/** Brier skill vs the always-predict-the-mean baseline: positive = we beat it. */
function skill(brier: number | null, baseline: number | null): number | null {
  if (brier == null || baseline == null) return null
  return baseline - brier
}

function skillClass(s: number | null) {
  if (s == null) return 'text-zinc-500'
  if (s > 0.002) return 'text-emerald-400 font-semibold'
  if (s > 0) return 'text-emerald-300'
  if (s > -0.002) return 'text-zinc-400'
  return 'text-rose-300'
}

export function AccuracyBoard() {
  const [days, setDays] = useState<number>(30)
  const { data, isPending, isError } = useQuery(accuracyQueryOptions(days))

  const markets: MarketAccuracy[] = data?.markets ?? []

  return (
    <section className="mt-14">
      <div className={microLabel}>Every projection — not just the ones we bet</div>
      <h2 className="text-xl font-bold tracking-tight text-zinc-100 mt-1 mb-2">
        Projection Calibration
      </h2>
      <p className="text-sm text-zinc-400 mb-5 max-w-2xl">
        How well our projections matched reality, scored each day against final stats — across
        <em> all</em> projected players, an unbiased read on the model itself. Lower Brier is
        better; <span className="text-emerald-300">skill</span> is how much we beat the naive
        always-predict-the-average baseline. Calibration shows whether a projected probability
        matches the rate things actually happened.
      </p>

      <div className="flex items-center justify-between mb-5">
        <div className="flex gap-1.5">
          {WINDOWS.map((w) => (
            <button
              key={w}
              type="button"
              onClick={() => setDays(w)}
              className={cn(
                'px-2.5 py-1 rounded-md text-xs font-medium transition-colors',
                days === w
                  ? 'bg-cyan-400/15 text-cyan-300 ring-1 ring-cyan-400/30'
                  : 'text-zinc-400 hover:text-zinc-100 hover:bg-white/5',
              )}
            >
              {w}d
            </button>
          ))}
        </div>
        {data?.modelVersion && (
          <div className="text-xs text-zinc-500 font-mono">model {data.modelVersion}</div>
        )}
      </div>

      {isPending && <div className="text-sm text-zinc-500">Loading accuracy…</div>}
      {isError && <div className="text-sm text-rose-300">Failed to load accuracy.</div>}
      {!isPending && !isError && markets.length === 0 && (
        <div className="text-sm text-zinc-500">
          No accuracy snapshots yet. Run <code className="text-zinc-400">compute-accuracy</code> for a
          past slate to populate this board.
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-2">
        {markets.map((m) => (
          <MarketCard key={m.market} market={m} />
        ))}
      </div>
    </section>
  )
}

function MarketCard({ market }: { market: MarketAccuracy }) {
  const label = MARKET_LABEL[market.market] ?? market.market
  const latest = market.series[market.series.length - 1]
  const isRuns = market.market === 'total_runs'
  const latestSkill = skill(latest?.brier ?? null, latest?.baselineBrier ?? null)
  const skillText =
    latestSkill == null ? '—' : (latestSkill >= 0 ? '+' : '') + (latestSkill * 1000).toFixed(1)

  return (
    <div className="rounded-xl border border-white/10 bg-white/[0.02] p-4">
      <div className="flex items-baseline justify-between mb-3">
        <div>
          <div className={microLabel}>Market</div>
          <h2 className="text-base font-semibold text-zinc-100">{label}</h2>
        </div>
        {isRuns ? (
          <div className="text-right">
            <div className={microLabel}>Run MAE</div>
            <div className="text-lg font-mono text-zinc-100">
              {market.mae != null ? market.mae.toFixed(2) : '—'}
            </div>
          </div>
        ) : (
          <div className="text-right">
            <div className={microLabel}>Skill ×10³</div>
            <div className={cn('text-lg font-mono', skillClass(latestSkill))}>{skillText}</div>
          </div>
        )}
      </div>

      {isRuns ? (
        <p className="text-xs text-zinc-500">
          Average absolute miss on a game&apos;s total runs over the window
          {latest ? ` (latest slate n=${latest.n})` : ''}.
        </p>
      ) : (
        <>
          <BrierTrend market={market} />
          <CalibrationChart market={market} />
        </>
      )}
    </div>
  )
}

function BrierTrend({ market }: { market: MarketAccuracy }) {
  const chartData = market.series
    .filter((p) => p.brier != null)
    .map((p) => ({
      date: fmtDate(p.date),
      brier: p.brier,
      baseline: p.baselineBrier,
    }))

  if (chartData.length === 0) {
    return <div className="text-xs text-zinc-600 py-6">Not enough scored days yet.</div>
  }

  return (
    <div className="mt-1">
      <div className={cn(microLabel, 'mb-1')}>Brier vs baseline</div>
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
          <XAxis dataKey="date" tick={{ fontSize: 10, fill: '#a1a1aa' }} interval="preserveStartEnd" />
          <YAxis tick={{ fontSize: 10, fill: '#a1a1aa' }} domain={['auto', 'auto']} width={44} />
          <Tooltip
            contentStyle={{
              background: '#15171c',
              border: '1px solid #ffffff20',
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: '#e4e4e7' }}
          />
          <Line type="monotone" dataKey="baseline" stroke="#71717a" strokeWidth={1.5} dot={false} name="baseline" />
          <Line type="monotone" dataKey="brier" stroke="#22d3ee" strokeWidth={2} dot={false} name="model" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}

function CalibrationChart({ market }: { market: MarketAccuracy }) {
  const points = market.calibration
    .filter((b) => b.n > 0)
    .map((b) => {
      const predicted = Math.round(b.predictedMean * 1000) / 10
      return {
        predicted,
        actual: Math.round(b.actualRate * 1000) / 10,
        ideal: predicted, // a perfectly-calibrated model sits on actual = predicted
      }
    })
    .sort((a, b) => a.predicted - b.predicted)

  if (points.length < 2) return null

  return (
    <div className="mt-3">
      <div className={cn(microLabel, 'mb-1')}>Calibration — predicted % vs actual %</div>
      <ResponsiveContainer width="100%" height={150}>
        <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
          <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
          <XAxis
            dataKey="predicted"
            type="number"
            domain={[0, 100]}
            tick={{ fontSize: 10, fill: '#a1a1aa' }}
            width={44}
          />
          <YAxis domain={[0, 100]} tick={{ fontSize: 10, fill: '#a1a1aa' }} width={44} />
          <Tooltip
            contentStyle={{
              background: '#15171c',
              border: '1px solid #ffffff20',
              borderRadius: 8,
              fontSize: 12,
            }}
            labelStyle={{ color: '#e4e4e7' }}
            formatter={(value) => `${value}%`}
          />
          <Line
            type="linear"
            dataKey="ideal"
            stroke="#52525b"
            strokeWidth={1}
            strokeDasharray="4 4"
            dot={false}
            name="ideal"
          />
          <Line type="monotone" dataKey="actual" stroke="#34d399" strokeWidth={2} dot={{ r: 2 }} name="actual" />
        </LineChart>
      </ResponsiveContainer>
    </div>
  )
}
