import type { BatterProjection } from '@/lib/types'
import { cn } from '@/lib/utils'
import { dedupeArsenal, dedupeVsArsenal, STAT_INFO } from './batter-stats'
import { PITCH_NAMES } from './ui'
import { microLabel } from '@/components/ui/primitives'

/**
 * How the batter fares against each pitch the opposing starter throws.
 * Arsenal + batter-vs-arsenal rows are deduped by pitch type (the API can
 * return the same pitch twice — see plan §8).
 */
export function ArsenalDetail({ b }: { b: BatterProjection }) {
  const vs = dedupeVsArsenal(b.batterVsArsenal)
  const usageByType = new Map(dedupeArsenal(b.pitcherArsenal).map((a) => [a.pitchType, a]))

  if (vs.length === 0) {
    return <p className="text-xs text-zinc-400">No pitch-type matchup data for this batter.</p>
  }

  return (
    <div>
      <div className={cn(microLabel, 'mb-2')}>vs {b.opposingPitcher.name}&apos;s arsenal</div>
      <table className="w-full text-xs">
        <thead>
          <tr className={microLabel}>
            <th className="text-left py-1 font-medium">Pitch</th>
            <th className="text-right py-1 font-medium" title={STAT_INFO['Uses']}>Uses</th>
            <th className="text-right py-1 font-medium" title="Batter's regressed xwOBA on this pitch">
              Batter xwOBA
            </th>
            <th className="text-right py-1 font-medium" title={STAT_INFO['League']}>League</th>
            <th className="text-right py-1 font-medium" title={STAT_INFO['Edge']}>Edge</th>
          </tr>
        </thead>
        <tbody>
          {vs.map((row) => {
            const ars = usageByType.get(row.pitchType)
            const positive = row.edge != null && row.edge.startsWith('+')
            return (
              <tr key={row.pitchType} className="border-t border-white/5">
                <td className="py-1 text-zinc-200">{PITCH_NAMES[row.pitchType] ?? row.pitchType}</td>
                <td className="py-1 text-right font-mono tabular-nums text-zinc-400">
                  {ars?.usageRate != null ? `${(ars.usageRate * 100).toFixed(0)}%` : '—'}
                </td>
                <td className="py-1 text-right font-mono tabular-nums text-zinc-200">
                  {row.xwobaRegressed != null ? row.xwobaRegressed.toFixed(3) : '—'}
                </td>
                <td className="py-1 text-right font-mono tabular-nums text-zinc-500">
                  {ars?.leagueXwoba != null ? ars.leagueXwoba.toFixed(3) : '—'}
                </td>
                <td
                  className={cn(
                    'py-1 text-right font-mono tabular-nums font-medium',
                    positive ? 'text-emerald-400' : 'text-rose-400',
                  )}
                >
                  {row.edge ?? '—'} {positive ? '✓' : '✗'}
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}
