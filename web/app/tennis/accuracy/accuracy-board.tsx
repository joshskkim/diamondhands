'use client'

import { useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { tennisAccuracyQueryOptions, type TennisAccuracy } from '@/lib/tennis-api'
import { cn } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'
const SURFACES = ['all', 'hard', 'clay', 'grass'] as const

function BrierChart({ data }: { data: TennisAccuracy }) {
  const chartData = data.series.map((p) => ({
    period: p.period.slice(0, 7),
    brier: p.brier,
    baseline: p.baselineBrier,
  }))
  return (
    <ResponsiveContainer width="100%" height={170}>
      <LineChart data={chartData} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
        <CartesianGrid stroke="#ffffff10" vertical={false} />
        <XAxis dataKey="period" tick={{ fill: '#71717a', fontSize: 10 }} tickLine={false} axisLine={false} />
        <YAxis tick={{ fill: '#71717a', fontSize: 10 }} tickLine={false} axisLine={false} domain={[0.15, 0.27]} />
        <Tooltip
          contentStyle={{ background: '#0e1015', border: '1px solid #ffffff20', borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: '#a1a1aa' }}
        />
        <Line type="monotone" dataKey="baseline" stroke="#71717a" strokeWidth={1.5} dot={false} name="baseline" />
        <Line type="monotone" dataKey="brier" stroke="#22d3ee" strokeWidth={2} dot={false} name="model" />
      </LineChart>
    </ResponsiveContainer>
  )
}

function CalibrationChart({ data }: { data: TennisAccuracy }) {
  const points = data.calibration.map((b) => ({
    predicted: Math.round(b.predictedMean * 100),
    actual: Math.round(b.actualRate * 100),
    ideal: Math.round(b.predictedMean * 100),
  }))
  return (
    <ResponsiveContainer width="100%" height={170}>
      <LineChart data={points} margin={{ top: 4, right: 8, bottom: 0, left: -20 }}>
        <CartesianGrid stroke="#ffffff10" vertical={false} />
        <XAxis dataKey="predicted" tick={{ fill: '#71717a', fontSize: 10 }} tickLine={false} axisLine={false}
               domain={[0, 100]} type="number" />
        <YAxis tick={{ fill: '#71717a', fontSize: 10 }} tickLine={false} axisLine={false} domain={[0, 100]} />
        <Tooltip
          contentStyle={{ background: '#0e1015', border: '1px solid #ffffff20', borderRadius: 8, fontSize: 12 }}
          labelStyle={{ color: '#a1a1aa' }}
        />
        <Line type="monotone" dataKey="ideal" stroke="#52525b" strokeWidth={1} strokeDasharray="4 4" dot={false} name="ideal" />
        <Line type="monotone" dataKey="actual" stroke="#34d399" strokeWidth={2} dot={{ r: 2 }} name="actual" />
      </LineChart>
    </ResponsiveContainer>
  )
}

function latestSkill(data: TennisAccuracy): number | null {
  const withBrier = data.series.filter((p) => p.brier != null && p.baselineBrier != null)
  if (withBrier.length === 0) return null
  const totN = withBrier.reduce((s, p) => s + p.n, 0)
  // Sample-weighted skill = baseline − model Brier (positive = beating the naive baseline).
  const skill = withBrier.reduce((s, p) => s + (p.baselineBrier! - p.brier!) * p.n, 0) / totN
  return skill
}

export function TennisAccuracyBoard() {
  const [surface, setSurface] = useState<(typeof SURFACES)[number]>('all')
  const { data, isLoading, isError } = useQuery(tennisAccuracyQueryOptions(surface))
  const skill = data ? latestSkill(data) : null

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8">
      <p className={microLabel}>ATP · Out-of-sample (2024+)</p>
      <h1 className="mt-1 text-3xl text-zinc-100">Accuracy</h1>
      <p className="mt-2 max-w-xl text-sm text-zinc-400">
        Walk-forward match-winner performance: Brier score vs an always-base-rate
        baseline, and calibration (predicted vs actual win rate).
      </p>

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

      {isLoading && <p className="mt-6 text-sm text-zinc-500">Loading…</p>}
      {isError && <p className="mt-6 text-sm text-rose-400">Couldn&apos;t load accuracy.</p>}
      {data && data.series.length === 0 && (
        <p className="mt-6 text-sm text-zinc-500">No scored matches yet for this surface.</p>
      )}

      {data && data.series.length > 0 && (
        <div className="mt-6 space-y-6">
          {skill != null && (
            <div className="rounded-xl border border-white/10 bg-[#0e1015] p-4">
              <span className={microLabel}>Skill vs baseline (Brier)</span>
              <div className={cn('mt-1 font-mono text-2xl', skill > 0.002 ? 'text-emerald-400' : skill < -0.002 ? 'text-rose-400' : 'text-zinc-300')}>
                {skill > 0 ? '+' : ''}{skill.toFixed(4)}
              </div>
            </div>
          )}
          <div className="rounded-xl border border-white/10 bg-[#0e1015] p-4">
            <p className={microLabel}>Brier — model vs baseline (lower is better)</p>
            <div className="mt-3"><BrierChart data={data} /></div>
          </div>
          <div className="rounded-xl border border-white/10 bg-[#0e1015] p-4">
            <p className={microLabel}>Calibration — actual vs predicted win rate</p>
            <div className="mt-3"><CalibrationChart data={data} /></div>
          </div>
        </div>
      )}
    </main>
  )
}
