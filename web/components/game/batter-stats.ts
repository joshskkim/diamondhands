import type { BatterProjection, BatterVsArsenal, PitchArsenal, Adjustments } from '@/lib/types'

// ── formatting ────────────────────────────────────────────────────────────

export function fixed2(v: number | null | undefined) {
  if (v == null) return '—'
  return v.toFixed(2)
}

// ── color scales ────────────────────────────────────────────────────────────

// Positive heat scale (more likely = warmer green). Used for hit / HR cells.
export function hrClass(p: number) {
  if (p > 0.12) return 'text-emerald-400 font-semibold'
  if (p > 0.08) return 'text-emerald-300'
  if (p >= 0.05) return 'text-zinc-300'
  return 'text-zinc-500'
}

export function hitClass(p: number) {
  if (p > 0.75) return 'text-emerald-400 font-semibold'
  if (p > 0.6) return 'text-emerald-300'
  if (p < 0.5) return 'text-zinc-500'
  return 'text-zinc-300'
}

// K% inverts: a high strikeout chance is a negative outcome for the batter.
export function kClass(p: number) {
  if (p > 0.6) return 'text-rose-400 font-semibold'
  if (p > 0.45) return 'text-rose-300'
  return 'text-zinc-400'
}

// ── adjustment decomposition ──────────────────────────────────────────────────

function pitcherQualityLabel(q: string | null): string {
  if (q === 'matchup') return 'Matchup sample'
  if (q === 'overall') return 'Overall pitcher stats'
  if (q === 'league_avg') return 'Unknown pitcher (league avg)'
  return ''
}

// Decompose a final probability into its base × multiplier chain.
export function adjParts(finalVal: number, adjs: Adjustments, isHr: boolean) {
  const w = isHr ? adjs.weatherHr : adjs.weatherHit
  const park = adjs.park ?? 1
  const pitcher = adjs.pitcher ?? 1
  const weather = w ?? 1
  const combined = park * pitcher * weather
  const base = combined !== 0 ? finalVal / combined : finalVal
  return { base, park, pitcher, weather }
}

export function adjTooltip(
  finalVal: number,
  adjs: Adjustments,
  isHr: boolean,
  pitcherDataQuality: string | null,
): string {
  const { base, park, pitcher, weather } = adjParts(finalVal, adjs, isHr)
  const f = (n: number | null | undefined) => (n != null ? n.toFixed(3) : '—')
  const breakdown = `Base: ${f(base)} · Park ×${f(park)} · Pitcher ×${f(pitcher)} · Weather ×${f(weather)} → ${f(finalVal)}`
  const ql = pitcherQualityLabel(pitcherDataQuality)
  return ql ? `${breakdown}\n${ql}` : breakdown
}

// Compact, always-visible adjustment hint (Park · Pitcher · Wx multipliers).
export function adjHint(b: BatterProjection): string {
  const { park, pitcher, weather } = adjParts(b.probabilities.hit1plus, b.adjustments, false)
  const f = (n: number) => n.toFixed(2)
  return `Park ×${f(park)} · Pitcher ×${f(pitcher)} · Wx ×${f(weather)}`
}

export function matchupNote(b: BatterProjection): string {
  if (b.matchupXwoba == null) return ''
  const q = b.matchupQuality === 'matchup' ? "vs pitcher's mix" : 'season blend (no arsenal)'
  return `Matchup xwOBA: ${b.matchupXwoba.toFixed(3)} (${q})`
}

// ── dedupe (works around the API season-pinning dupe; see plan §8) ────────────

/**
 * Collapse an arsenal that may contain the same pitch type more than once
 * (two seasons share an as_of_date in the snapshot data). Usage + leagueXwoba
 * are averaged across the duplicate rows; output is sorted by usage desc.
 */
export function dedupeArsenal(arsenal: PitchArsenal[] | null | undefined): PitchArsenal[] {
  const byType = new Map<string, { usage: number[]; xwoba: number[] }>()
  for (const a of arsenal ?? []) {
    if (a.usageRate == null || a.usageRate <= 0) continue
    const agg = byType.get(a.pitchType) ?? { usage: [], xwoba: [] }
    agg.usage.push(a.usageRate)
    if (a.leagueXwoba != null) agg.xwoba.push(a.leagueXwoba)
    byType.set(a.pitchType, agg)
  }
  const avg = (xs: number[]) => (xs.length ? xs.reduce((s, x) => s + x, 0) / xs.length : null)
  return [...byType.entries()]
    .map(([pitchType, agg]) => ({
      pitchType,
      usageRate: avg(agg.usage),
      leagueXwoba: avg(agg.xwoba),
    }))
    .sort((a, b) => (b.usageRate ?? 0) - (a.usageRate ?? 0))
}

/** Collapse duplicate batter-vs-pitch rows by pitch type (dup rows are identical). */
export function dedupeVsArsenal(vs: BatterVsArsenal[] | null | undefined): BatterVsArsenal[] {
  const seen = new Set<string>()
  const out: BatterVsArsenal[] = []
  for (const row of vs ?? []) {
    if (seen.has(row.pitchType)) continue
    seen.add(row.pitchType)
    out.push(row)
  }
  return out
}

// ── stat glossary (hover descriptions) ────────────────────────────────────────

export const STAT_INFO: Record<string, string> = {
  xPA: 'Expected plate appearances',
  'P(H≥1)': 'Chance of getting at least 1 hit',
  'P(H≥2)': 'Chance of getting 2 or more hits',
  'P(HR)': 'Chance of hitting a home run',
  'P(K)': 'Chance of striking out at least once',
  xH: 'Expected hits',
  xTB: 'Expected total bases',
  Uses: 'Share of pitches the pitcher throws of this type',
  League: 'League-average xwOBA against this pitch',
  Edge: "Batter's regressed xwOBA on this pitch minus the league baseline",
  Velo: 'Average velocity (mph)',
  'Whiff%': 'Swing-and-miss rate on this pitch',
  'xwOBA-against': "Hitters' xwOBA against this pitch",
  'K%': 'Strikeout rate (per batter faced)',
  'BB%': 'Walk rate (per batter faced)',
  'HR/PA': 'Home runs allowed per plate appearance',
}
