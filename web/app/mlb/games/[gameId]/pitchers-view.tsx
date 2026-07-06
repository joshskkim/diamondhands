import Link from 'next/link'
import type { BatterProjection, GameProjections, PitcherDetail } from '@/lib/types'
import { PitcherArsenalCard } from '@/components/game/pitcher-arsenal-card'
import { microLabel } from '@/components/ui/primitives'

function xwoba(v: number) {
  return v.toFixed(3).replace(/^0/, '')
}

// PA-weighted average matchup xwOBA of the lineup this pitcher faces — the headline
// "how the offense projects against his mix" number, plus the toughest individual bats.
function lineupSummary(lineup: BatterProjection[]) {
  const rated = lineup.filter((b) => b.matchupXwoba != null && b.expectedPa > 0)
  if (rated.length === 0) return null
  const totPa = rated.reduce((s, b) => s + b.expectedPa, 0)
  const weighted = rated.reduce((s, b) => s + (b.matchupXwoba as number) * b.expectedPa, 0) / totPa
  const byThreat = [...rated].sort(
    (a, b) => (b.matchupXwoba as number) - (a.matchupXwoba as number),
  )
  return {
    weighted,
    n: rated.length,
    toughest: byThreat.slice(0, 3),
    easiest: byThreat.slice(-3).reverse(),
  }
}

function MatchupPanel({
  pitcherName,
  lineupName,
  lineup,
}: {
  pitcherName: string
  lineupName: string
  lineup: BatterProjection[]
}) {
  const s = lineupSummary(lineup)
  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl p-4">
      <div className={microLabel}>vs the {lineupName} lineup</div>
      {s == null ? (
        <p className="mt-2 text-sm text-zinc-500">
          No pitch-type matchup data for this lineup yet.
        </p>
      ) : (
        <>
          <div className="mt-2 flex items-baseline gap-2">
            <span className="font-mono tabular-nums text-2xl text-zinc-100">
              {xwoba(s.weighted)}
            </span>
            <span className="text-xs text-zinc-500">
              PA-weighted matchup xwOBA the offense projects against {pitcherName}&apos;s mix
              ({s.n} bats)
            </span>
          </div>
          <div className="mt-4 grid grid-cols-1 sm:grid-cols-2 gap-4">
            <BatList label="Toughest matchups" bats={s.toughest} tone="bad" />
            <BatList label="Best matchups" bats={s.easiest} tone="good" />
          </div>
        </>
      )}
    </div>
  )
}

function BatList({
  label,
  bats,
  tone,
}: {
  label: string
  bats: BatterProjection[]
  tone: 'good' | 'bad'
}) {
  return (
    <div>
      <div className={microLabel}>{label}</div>
      <ul className="mt-1.5 space-y-1">
        {bats.map((b) => (
          <li key={b.player.id} className="flex items-center justify-between gap-2 text-sm">
            <Link
              href={`/mlb/players/${b.player.id}`}
              className="truncate text-zinc-200 hover:text-cyan-400 transition-colors"
            >
              {b.player.name}
              {b.player.bats && <span className="text-zinc-500"> ({b.player.bats})</span>}
            </Link>
            <span
              className={`shrink-0 font-mono tabular-nums ${
                tone === 'bad' ? 'text-rose-300' : 'text-emerald-300'
              }`}
            >
              {b.matchupXwoba != null ? xwoba(b.matchupXwoba) : '—'}
            </span>
          </li>
        ))}
      </ul>
    </div>
  )
}

// One starter column: arsenal breakdown + how the lineup he faces projects against it.
function PitcherColumn({
  pitcher,
  lineupName,
  lineup,
}: {
  pitcher: PitcherDetail | null
  lineupName: string
  lineup: BatterProjection[]
}) {
  if (pitcher == null) {
    return (
      <div className="bg-[#0e1015] border border-white/10 rounded-xl px-4 py-6">
        <p className="text-sm text-zinc-500">Probable starter not announced yet.</p>
      </div>
    )
  }
  return (
    <div className="space-y-6">
      <PitcherArsenalCard
        name={pitcher.name}
        throws={pitcher.throws}
        teamAbbr={pitcher.teamAbbr}
        arsenal={pitcher.arsenal}
        skill={pitcher.skill}
      />
      <MatchupPanel pitcherName={pitcher.name} lineupName={lineupName} lineup={lineup} />
    </div>
  )
}

/**
 * Pitchers tab: both starters side by side. The home starter faces the away lineup and
 * vice-versa, so each column pairs a pitcher's arsenal with the opposing lineup's
 * projected matchup against it.
 */
export function PitchersView({
  data,
  homeName,
  awayName,
}: {
  data: GameProjections
  homeName: string
  awayName: string
}) {
  const pitchers = data.pitchers
  if (pitchers == null || (pitchers.home == null && pitchers.away == null)) {
    return (
      <p className="text-amber-300 bg-amber-400/10 border border-amber-400/30 rounded-xl p-4 text-sm">
        No probable starters available yet for this game.
      </p>
    )
  }
  return (
    <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
      <PitcherColumn pitcher={pitchers.home} lineupName={awayName} lineup={data.away.batters} />
      <PitcherColumn pitcher={pitchers.away} lineupName={homeName} lineup={data.home.batters} />
    </div>
  )
}
