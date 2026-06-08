'use client'

import { useState } from 'react'
import type { BatterProjection, TeamBatters } from '@/lib/types'
import { cn } from '@/lib/utils'
import { BatterDetail } from './batter-detail'
import { pct, STAT_INFO } from './batter-stats'
import { Chip, microLabel } from './ui'

// Confirmed lineups have a real batting order; projected ones do not (every
// batter shares a flat expected PA), so we never imply an order — we surface the
// most relevant bats first by hit probability instead. See plan §4.
function orderBatters(side: TeamBatters): BatterProjection[] {
  return side.lineupConfirmed
    ? [...side.batters].sort((a, b) => (a.lineupPosition ?? 99) - (b.lineupPosition ?? 99))
    : [...side.batters].sort((a, b) => (b.probabilities.hit1plus ?? 0) - (a.probabilities.hit1plus ?? 0))
}

function LineupList({
  teamName,
  side,
  selectedId,
  onSelect,
}: {
  teamName: string
  side: TeamBatters
  selectedId: number | null
  onSelect: (id: number) => void
}) {
  const ordered = orderBatters(side)
  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between gap-2">
        <span className="font-semibold tracking-tight text-zinc-100 text-sm">
          {teamName} <span className={microLabel}>{side.teamAbbr}</span>
        </span>
        {side.lineupConfirmed ? (
          <Chip tone="confirmed">Confirmed</Chip>
        ) : (
          <Chip tone="projected">Projected · order TBD</Chip>
        )}
      </div>
      {ordered.length > 0 ? (
        <ul className="divide-y divide-white/5">
          {ordered.map((b) => {
            const sel = b.player.id === selectedId
            return (
              <li key={b.player.id}>
                <button
                  onClick={() => onSelect(b.player.id)}
                  className={cn(
                    'w-full flex items-center gap-3 px-4 py-1.5 text-sm text-left transition-colors',
                    sel ? 'bg-cyan-400/10' : 'hover:bg-white/[0.03]',
                  )}
                >
                  <span className="w-4 text-right font-mono tabular-nums text-zinc-500">
                    {side.lineupConfirmed ? b.lineupPosition ?? '·' : '·'}
                  </span>
                  <span className={cn('font-medium', sel ? 'text-cyan-300' : 'text-zinc-200')}>
                    {b.player.name}
                  </span>
                  <span className="text-xs text-zinc-500">
                    {b.player.bats && `(${b.player.bats})`}
                  </span>
                  <span
                    className="ml-auto font-mono tabular-nums text-[11px] text-zinc-500"
                    title={STAT_INFO['P(H≥1)']}
                  >
                    {pct(b.probabilities.hit1plus)}
                  </span>
                </button>
              </li>
            )
          })}
        </ul>
      ) : (
        <p className="px-4 py-6 text-sm text-zinc-500">No batters available.</p>
      )}
    </div>
  )
}

/**
 * Master-detail Batters view: pick a batter from either lineup (left) to see all
 * their projection factors, what we like, and hot zones (right). Defaults to the
 * first home batter. Mounted with key={gameId} so selection resets per game.
 */
export function BattersTab({
  home,
  away,
  homeName,
  awayName,
}: {
  home: TeamBatters
  away: TeamBatters
  homeName: string
  awayName: string
}) {
  const homeOrdered = orderBatters(home)
  const awayOrdered = orderBatters(away)
  const all = [
    ...homeOrdered.map((b) => ({ b, abbr: home.teamAbbr })),
    ...awayOrdered.map((b) => ({ b, abbr: away.teamAbbr })),
  ]
  const [selectedId, setSelectedId] = useState<number | null>(homeOrdered[0]?.player.id ?? null)
  const selected = all.find((x) => x.b.player.id === selectedId) ?? all[0] ?? null

  if (all.length === 0) {
    return (
      <p className="text-amber-300 bg-amber-400/10 border border-amber-400/30 rounded-xl p-4 text-sm">
        Projection pending — probable pitchers or lineups not yet confirmed.
      </p>
    )
  }

  return (
    <div className="grid grid-cols-1 lg:grid-cols-[300px_1fr] gap-6">
      <div className="space-y-6">
        <LineupList
          teamName={homeName}
          side={home}
          selectedId={selected?.b.player.id ?? null}
          onSelect={setSelectedId}
        />
        <LineupList
          teamName={awayName}
          side={away}
          selectedId={selected?.b.player.id ?? null}
          onSelect={setSelectedId}
        />
      </div>
      {selected && <BatterDetail b={selected.b} teamAbbr={selected.abbr} />}
    </div>
  )
}
