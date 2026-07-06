import Link from 'next/link'
import type { BatterProjection } from '@/lib/types'
import { cn } from '@/lib/utils'
import { ArsenalDetail } from './arsenal-detail'
import {
  adjHint,
  dedupeVsArsenal,
  fixed2,
  hitClass,
  hrClass,
  kClass,
  matchupNote,
  STAT_INFO,
} from './batter-stats'
import { HotZoneGrid } from './hot-zone-grid'
import { PITCH_NAMES } from './ui'
import { microLabel } from '@/components/ui/primitives'
import { pct } from '@/lib/format'

type Insight = { tone: 'good' | 'bad'; text: string }

// A few concise, derived takeaways ("what we like / watch") from the projection.
function insights(b: BatterProjection): Insight[] {
  const out: Insight[] = []
  const p = b.probabilities
  const a = b.adjustments
  if (p.hit1plus >= 0.72) out.push({ tone: 'good', text: 'High hit chance' })
  if (p.hr >= 0.08) out.push({ tone: 'good', text: 'Power upside' })
  if (p.k1plus <= 0.4) out.push({ tone: 'good', text: 'Low strikeout risk' })
  if (p.k1plus >= 0.58) out.push({ tone: 'bad', text: 'Strikeout risk' })
  if (b.matchupXwoba != null && b.matchupXwoba >= 0.36)
    out.push({ tone: 'good', text: 'Strong matchup xwOBA' })
  if (b.matchupXwoba != null && b.matchupXwoba <= 0.29)
    out.push({ tone: 'bad', text: 'Tough matchup' })
  const goodPitches = dedupeVsArsenal(b.batterVsArsenal)
    .filter((r) => r.edge != null && r.edge.startsWith('+') && parseFloat(r.edge) >= 0.04)
    .map((r) => PITCH_NAMES[r.pitchType] ?? r.pitchType)
  if (goodPitches.length) out.push({ tone: 'good', text: `Edge vs ${goodPitches.slice(0, 2).join(', ')}` })
  if (a.park >= 1.05) out.push({ tone: 'good', text: 'Park boost' })
  if (a.weatherHr >= 1.05) out.push({ tone: 'good', text: 'Wind aids HR' })
  if (a.pitcher >= 1.06) out.push({ tone: 'good', text: 'Favorable pitcher' })
  if (a.pitcher <= 0.94) out.push({ tone: 'bad', text: 'Tough pitcher' })
  return out.slice(0, 6)
}

function StatTile({ label, value, cls }: { label: string; value: string; cls: string }) {
  return (
    <div className="rounded-lg bg-white/[0.03] border border-white/5 px-2.5 py-2" title={STAT_INFO[label]}>
      <div className={cn(microLabel, 'cursor-help')}>{label}</div>
      <div className={cn('mt-0.5 font-mono tabular-nums text-sm', cls)}>{value}</div>
    </div>
  )
}

export function BatterDetail({ b, teamAbbr }: { b: BatterProjection; teamAbbr: string }) {
  const p = b.probabilities
  const tips = insights(b)
  const stats: { label: string; value: string; cls: string }[] = [
    { label: 'xPA', value: fixed2(b.expectedPa), cls: 'text-zinc-200' },
    { label: 'P(H≥1)', value: pct(p.hit1plus), cls: hitClass(p.hit1plus) },
    { label: 'P(H≥2)', value: pct(p.hit2plus), cls: 'text-zinc-200' },
    { label: 'P(HR)', value: pct(p.hr), cls: hrClass(p.hr) },
    { label: 'P(K)', value: pct(p.k1plus), cls: kClass(p.k1plus) },
    { label: 'xH', value: fixed2(b.expectedHits), cls: 'text-zinc-200' },
    { label: 'xTB', value: fixed2(b.expectedTotalBases), cls: 'text-zinc-200' },
  ]

  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl p-5 space-y-5">
      {/* header */}
      <div className="flex flex-wrap items-baseline gap-2">
        <Link
          href={`/mlb/players/${b.player.id}`}
          className="text-lg font-semibold tracking-tight text-zinc-100 hover:text-cyan-400 transition-colors"
        >
          {b.player.name}
        </Link>
        <span className="text-[10px] font-semibold uppercase tracking-wide text-cyan-400/80">{teamAbbr}</span>
        <span className="text-xs text-zinc-500">
          {b.player.bats && `(${b.player.bats})`}
          {b.player.position && ` · ${b.player.position}`}
          {b.lineupPosition != null && ` · #${b.lineupPosition}`}
        </span>
        <span className="ml-auto text-xs text-zinc-500">
          vs <span className="text-zinc-300">{b.opposingPitcher.name}</span>{' '}
          {b.opposingPitcher.throws && (b.opposingPitcher.throws === 'L' ? 'LHP' : 'RHP')}
        </span>
      </div>

      {/* stat grid */}
      <div className="grid grid-cols-3 sm:grid-cols-4 lg:grid-cols-7 gap-2">
        {stats.map((s) => (
          <StatTile key={s.label} label={s.label} value={s.value} cls={s.cls} />
        ))}
      </div>

      {/* what we like / watch */}
      {tips.length > 0 && (
        <div>
          <div className={microLabel}>What we like / watch</div>
          <div className="mt-2 flex flex-wrap gap-1.5">
            {tips.map((t, i) => (
              <span
                key={i}
                className={cn(
                  'inline-flex items-center text-[11px] rounded px-1.5 py-0.5 border',
                  t.tone === 'good'
                    ? 'text-emerald-300 border-emerald-400/30 bg-emerald-400/10'
                    : 'text-rose-300 border-rose-400/30 bg-rose-400/10',
                )}
              >
                {t.text}
              </span>
            ))}
          </div>
        </div>
      )}

      {/* adjustment hint */}
      <div
        className="text-[11px] font-mono tabular-nums text-zinc-500"
        title={matchupNote(b) || undefined}
      >
        {adjHint(b)}
      </div>

      {/* pitch matchup + hot zones */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-5 pt-1 border-t border-white/10">
        <ArsenalDetail b={b} />
        <HotZoneGrid />
      </div>
    </div>
  )
}
