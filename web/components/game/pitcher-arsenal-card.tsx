'use client'

import type { PitchArsenal, PitcherSkillSplit } from '@/lib/types'
import { STAT_INFO } from './batter-stats'
import { PITCH_NAMES } from './ui'
import { microLabel } from '@/components/ui/primitives'

// Stable per-pitch colors for the usage bar + legend swatches.
const PITCH_COLORS: Record<string, string> = {
  FF: '#f43f5e', // 4-seam — rose
  SI: '#fb923c', // sinker — orange
  FC: '#a78bfa', // cutter — violet
  SL: '#facc15', // slider — yellow
  CU: '#38bdf8', // curve — sky
  CH: '#34d399', // change — emerald
  FS: '#2dd4bf', // splitter — teal
}

function pitchColor(code: string) {
  return PITCH_COLORS[code] ?? '#71717a'
}

const avg = (xs: number[]) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null)

type AggPitch = {
  pitchType: string
  usageRate: number
  leagueXwoba: number | null
  xwobaAgainst: number | null
  whiffRate: number | null
  avgVelocity: number | null
}

/**
 * One starter's pitch mix. Usage drives a normalized stacked bar; the legend
 * pairs each pitch with the league xwOBA baseline (and pitcher velocity / whiff%
 * / xwOBA-against once the API serves them). The arsenal can arrive split by
 * batter handedness, so each pitch is collapsed to a single averaged row.
 */
export function PitcherArsenalCard({
  name,
  throws,
  teamAbbr,
  arsenal,
  skill,
}: {
  name: string
  throws: string | null
  teamAbbr: string
  arsenal: PitchArsenal[]
  skill?: PitcherSkillSplit[]
}) {
  const byType = new Map<
    string,
    { usage: number[]; xwoba: number[]; xwAgainst: number[]; whiff: number[]; velo: number[] }
  >()
  for (const a of arsenal) {
    if (a.usageRate == null || a.usageRate <= 0) continue
    const agg = byType.get(a.pitchType) ?? { usage: [], xwoba: [], xwAgainst: [], whiff: [], velo: [] }
    agg.usage.push(a.usageRate)
    if (a.leagueXwoba != null) agg.xwoba.push(a.leagueXwoba)
    if (a.xwobaAgainst != null) agg.xwAgainst.push(a.xwobaAgainst)
    if (a.whiffRate != null) agg.whiff.push(a.whiffRate)
    if (a.avgVelocity != null) agg.velo.push(a.avgVelocity)
    byType.set(a.pitchType, agg)
  }
  const pitches: AggPitch[] = [...byType.entries()]
    .map(([pitchType, agg]) => ({
      pitchType,
      usageRate: avg(agg.usage) ?? 0,
      leagueXwoba: avg(agg.xwoba),
      xwobaAgainst: avg(agg.xwAgainst),
      whiffRate: avg(agg.whiff),
      avgVelocity: avg(agg.velo),
    }))
    .sort((a, b) => b.usageRate - a.usageRate)
  const total = pitches.reduce((s, a) => s + a.usageRate, 0) || 1

  // Light up the richer columns only when the API actually provides them.
  const hasVelo = pitches.some((p) => p.avgVelocity != null)
  const hasWhiff = pitches.some((p) => p.whiffRate != null)
  const hasXwAgainst = pitches.some((p) => p.xwobaAgainst != null)

  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
        <div className="flex items-baseline gap-2">
          <span className="font-semibold tracking-tight text-zinc-100">{name}</span>
          <span className="text-[10px] font-semibold uppercase tracking-wide text-cyan-400/80">
            {teamAbbr}
          </span>
        </div>
        {throws && <span className={microLabel}>{throws === 'L' ? 'LHP' : 'RHP'}</span>}
      </div>

      <div className="p-4 space-y-4">
        {pitches.length > 0 ? (
          <>
            {/* usage bar */}
            <div className="flex h-2.5 rounded overflow-hidden gap-px bg-black/40">
              {pitches.map((p) => (
                <div
                  key={p.pitchType}
                  style={{
                    width: `${(p.usageRate / total) * 100}%`,
                    backgroundColor: pitchColor(p.pitchType),
                  }}
                  title={`${PITCH_NAMES[p.pitchType] ?? p.pitchType} · ${(p.usageRate * 100).toFixed(0)}%`}
                />
              ))}
            </div>

            {/* legend */}
            <table className="w-full text-xs">
              <thead>
                <tr className={microLabel}>
                  <th className="text-left py-1 font-medium">Pitch</th>
                  <th className="text-right py-1 font-medium" title={STAT_INFO['Uses']}>Usage</th>
                  {hasVelo && <th className="text-right py-1 font-medium" title={STAT_INFO['Velo']}>Velo</th>}
                  {hasWhiff && <th className="text-right py-1 font-medium" title={STAT_INFO['Whiff%']}>Whiff%</th>}
                  {hasXwAgainst && (
                    <th className="text-right py-1 font-medium" title={STAT_INFO['xwOBA-against']}>xwOBA</th>
                  )}
                  <th className="text-right py-1 font-medium" title={STAT_INFO['League']}>League</th>
                </tr>
              </thead>
              <tbody>
                {pitches.map((p) => (
                  <tr key={p.pitchType} className="border-t border-white/5">
                    <td className="py-1.5">
                      <span className="inline-flex items-center gap-1.5 text-zinc-200">
                        <span
                          className="inline-block h-2.5 w-2.5 rounded-sm"
                          style={{ backgroundColor: pitchColor(p.pitchType) }}
                        />
                        {PITCH_NAMES[p.pitchType] ?? p.pitchType}
                      </span>
                    </td>
                    <td className="py-1.5 text-right font-mono tabular-nums text-zinc-300">
                      {(p.usageRate * 100).toFixed(0)}%
                    </td>
                    {hasVelo && (
                      <td className="py-1.5 text-right font-mono tabular-nums text-zinc-300">
                        {p.avgVelocity != null ? p.avgVelocity.toFixed(1) : '—'}
                      </td>
                    )}
                    {hasWhiff && (
                      <td className="py-1.5 text-right font-mono tabular-nums text-zinc-300">
                        {p.whiffRate != null ? `${(p.whiffRate * 100).toFixed(0)}%` : '—'}
                      </td>
                    )}
                    {hasXwAgainst && (
                      <td className="py-1.5 text-right font-mono tabular-nums text-zinc-200">
                        {p.xwobaAgainst != null ? p.xwobaAgainst.toFixed(3) : '—'}
                      </td>
                    )}
                    <td className="py-1.5 text-right font-mono tabular-nums text-zinc-400">
                      {p.leagueXwoba != null ? p.leagueXwoba.toFixed(3) : '—'}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        ) : (
          <p className="text-sm text-zinc-500">No arsenal data for this pitcher.</p>
        )}

        {/* season splits vs LHB / RHB */}
        <SkillSplits skill={skill} />
      </div>
    </div>
  )
}

function SkillSplits({ skill }: { skill?: PitcherSkillSplit[] }) {
  if (!skill || skill.length === 0) {
    return (
      <div className="rounded-lg border border-dashed border-cyan-400/30 bg-cyan-400/[0.03] px-3 py-3 text-center">
        <div className="text-[11px] font-semibold text-cyan-300">Season splits vs LHB / RHB</div>
        <div className="text-[10px] text-zinc-500 mt-0.5">K%, BB%, xwOBA-against, HR/PA — coming soon</div>
      </div>
    )
  }
  return (
    <div>
      <div className={microLabel}>Season splits</div>
      <table className="w-full text-xs mt-2">
        <thead>
          <tr className={microLabel}>
            <th className="text-left py-1 font-medium">vs</th>
            <th className="text-right py-1 font-medium" title={STAT_INFO['K%']}>K%</th>
            <th className="text-right py-1 font-medium" title={STAT_INFO['BB%']}>BB%</th>
            <th className="text-right py-1 font-medium" title={STAT_INFO['xwOBA-against']}>xwOBA</th>
            <th className="text-right py-1 font-medium" title={STAT_INFO['HR/PA']}>HR/PA</th>
          </tr>
        </thead>
        <tbody>
          {skill.map((s) => (
            <tr key={s.vsHand} className="border-t border-white/5">
              <td className="py-1.5 text-zinc-200">{s.vsHand === 'L' ? 'LHB' : 'RHB'}</td>
              <td className="py-1.5 text-right font-mono tabular-nums text-zinc-300">
                {s.kRate != null ? `${(s.kRate * 100).toFixed(0)}%` : '—'}
              </td>
              <td className="py-1.5 text-right font-mono tabular-nums text-zinc-300">
                {s.bbRate != null ? `${(s.bbRate * 100).toFixed(0)}%` : '—'}
              </td>
              <td className="py-1.5 text-right font-mono tabular-nums text-zinc-200">
                {s.xwobaAgainst != null ? s.xwobaAgainst.toFixed(3) : '—'}
              </td>
              <td className="py-1.5 text-right font-mono tabular-nums text-zinc-300">
                {s.hrPerPa != null ? s.hrPerPa.toFixed(3) : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
