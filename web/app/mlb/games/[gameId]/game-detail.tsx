'use client'

import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ArrowLeft, ArrowUp, ChevronDown, ChevronRight, Info } from 'lucide-react'
import Link from 'next/link'
import { Fragment, useState } from 'react'
import { api } from '@/lib/api'
import type { BatterProjection, Adjustments } from '@/lib/types'
import { cn, parseApiDate } from '@/lib/utils'
import { OddsPanel } from './odds-panel'

// ── helpers ─────────────────────────────────────────────────────────────────

function pct(v: number | null | undefined) {
  if (v == null) return '—'
  return (v * 100).toFixed(1) + '%'
}

function fixed2(v: number | null | undefined) {
  if (v == null) return '—'
  return v.toFixed(2)
}

// Positive heat scale (more likely = warmer green). Used for hit / HR cells.
function hrClass(p: number) {
  if (p > 0.12) return 'text-emerald-400 font-semibold'
  if (p > 0.08) return 'text-emerald-300'
  if (p >= 0.05) return 'text-zinc-300'
  return 'text-zinc-500'
}

function hitClass(p: number) {
  if (p > 0.75) return 'text-emerald-400 font-semibold'
  if (p > 0.6) return 'text-emerald-300'
  if (p < 0.5) return 'text-zinc-500'
  return 'text-zinc-300'
}

// K% inverts: a high strikeout chance is a negative outcome for the batter.
function kClass(p: number) {
  if (p > 0.6) return 'text-rose-400 font-semibold'
  if (p > 0.45) return 'text-rose-300'
  return 'text-zinc-400'
}

type SortCol = 'lineup' | 'hit1plus' | 'hit2plus' | 'hr' | 'k1plus'

function pitcherQualityLabel(q: string | null): string {
  if (q === 'matchup') return 'Matchup sample'
  if (q === 'overall') return 'Overall pitcher stats'
  if (q === 'league_avg') return 'Unknown pitcher (league avg)'
  return ''
}

// Decompose a final probability into its base × multiplier chain.
function adjParts(finalVal: number, adjs: Adjustments, isHr: boolean) {
  const w = isHr ? adjs.weatherHr : adjs.weatherHit
  const park = adjs.park ?? 1
  const pitcher = adjs.pitcher ?? 1
  const weather = w ?? 1
  // Opposing-team defense scales the hit side only — a HR is never fielded.
  const defense = isHr ? 1 : (adjs.defense ?? 1)
  const combined = park * pitcher * weather * defense
  const base = combined !== 0 ? finalVal / combined : finalVal
  return { base, park, pitcher, weather, defense }
}

function adjTooltip(
  finalVal: number,
  adjs: Adjustments,
  isHr: boolean,
  pitcherDataQuality: string | null,
): string {
  const { base, park, pitcher, weather, defense } = adjParts(finalVal, adjs, isHr)
  const f = (n: number | null | undefined) => (n != null ? n.toFixed(3) : '—')
  // Defense only moves the hit side; omit the term when neutral so HR tooltips stay clean.
  const def = !isHr && Math.abs(defense - 1) >= 0.005 ? ` · Defense ×${f(defense)}` : ''
  const breakdown = `Base: ${f(base)} · Park ×${f(park)} · Pitcher ×${f(pitcher)} · Weather ×${f(weather)}${def} → ${f(finalVal)}`
  const ql = pitcherQualityLabel(pitcherDataQuality)
  return ql ? `${breakdown}\n${ql}` : breakdown
}

// Compact, always-visible adjustment hint shown beneath the player name so the
// breakdown is discoverable without hovering each cell.
function adjHint(b: BatterProjection): string {
  const { park, pitcher, weather, defense } = adjParts(b.probabilities.hit1plus, b.adjustments, false)
  const f = (n: number) => n.toFixed(2)
  const def = Math.abs(defense - 1) >= 0.005 ? ` · Def ×${f(defense)}` : ''
  return `Park ×${f(park)} · Pitcher ×${f(pitcher)} · Wx ×${f(weather)}${def}`
}

const PITCH_NAMES: Record<string, string> = {
  FF: '4-Seam', SI: 'Sinker', FC: 'Cutter', SL: 'Slider',
  CU: 'Curve', CH: 'Change', FS: 'Splitter',
}

function matchupNote(b: BatterProjection): string {
  if (b.matchupXwoba == null) return ''
  const q = b.matchupQuality === 'matchup' ? "vs pitcher's mix" : 'season blend (no arsenal)'
  return `Matchup xwOBA: ${b.matchupXwoba.toFixed(3)} (${q})`
}

// ── chips ─────────────────────────────────────────────────────────────────

const chipBase =
  'inline-flex items-center gap-1 text-[11px] rounded px-1.5 py-0.5 border'

function Chip({
  tone = 'neutral',
  className,
  children,
}: {
  tone?: 'neutral' | 'confirmed' | 'projected' | 'info'
  className?: string
  children: React.ReactNode
}) {
  const tones = {
    neutral: 'bg-white/5 border-white/10 text-zinc-300',
    confirmed: 'text-emerald-300 border-emerald-400/30 bg-emerald-400/10',
    projected: 'text-amber-300 border-amber-400/30 bg-amber-400/10',
    info: 'text-cyan-300 border-cyan-400/30 bg-cyan-400/10',
  }
  return <span className={cn(chipBase, tones[tone], className)}>{children}</span>
}

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

// Sortable column header. Hoisted to module scope so it isn't recreated each render.
function ColHeader({
  col,
  label,
  sortCol,
  sortDir,
  onSort,
}: {
  col: SortCol
  label: string
  sortCol: SortCol
  sortDir: 'asc' | 'desc'
  onSort: (col: SortCol) => void
}) {
  const active = sortCol === col
  return (
    <th
      className={cn(
        'px-2 py-2 text-right cursor-pointer select-none whitespace-nowrap transition-colors',
        microLabel,
        active ? 'text-cyan-400' : 'hover:text-zinc-300',
      )}
      onClick={() => onSort(col)}
    >
      {label}
      {active && <span className="ml-0.5">{sortDir === 'desc' ? '↓' : '↑'}</span>}
    </th>
  )
}

// Expanded per-batter view: how the batter fares against each pitch the SP throws.
function ArsenalDetail({ b }: { b: BatterProjection }) {
  const vs = b.batterVsArsenal ?? []
  const usageByType = new Map(
    (b.pitcherArsenal ?? []).map((a) => [a.pitchType, a]),
  )
  if (vs.length === 0) {
    return (
      <div className="px-4 py-3 bg-white/[0.03] text-xs text-zinc-400">
        No pitch-type matchup data for this batter.
      </div>
    )
  }
  return (
    <div className="px-4 py-3 bg-white/[0.03]">
      <div className={cn(microLabel, 'mb-2')}>
        vs {b.opposingPitcher.name}&apos;s arsenal
      </div>
      <table className="w-full max-w-lg text-xs">
        <thead>
          <tr className={microLabel}>
            <th className="text-left py-1 font-medium">Pitch</th>
            <th className="text-right py-1 font-medium">Uses</th>
            <th className="text-right py-1 font-medium">Batter xwOBA</th>
            <th className="text-right py-1 font-medium">League</th>
            <th className="text-right py-1 font-medium">Edge</th>
          </tr>
        </thead>
        <tbody>
          {vs.map((row) => {
            const ars = usageByType.get(row.pitchType)
            const positive = row.edge != null && row.edge.startsWith('+')
            return (
              <tr key={row.pitchType} className="border-t border-white/5">
                <td className="py-1 text-zinc-200">
                  {PITCH_NAMES[row.pitchType] ?? row.pitchType}
                </td>
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

// ── batter table ─────────────────────────────────────────────────────────────

function BatterTable({
  batters,
  sortCol,
  sortDir,
  onSort,
  showOrder,
}: {
  batters: BatterProjection[]
  sortCol: SortCol
  sortDir: 'asc' | 'desc'
  onSort: (col: SortCol) => void
  showOrder: boolean
}) {
  const [expanded, setExpanded] = useState<number | null>(null)
  const colSpan = showOrder ? 9 : 8
  const sorted = [...batters].sort((a, b) => {
    if (sortCol === 'lineup') {
      // Confirmed batting order ascending (1 → 9); unknowns sink to the bottom.
      return (a.lineupPosition ?? 99) - (b.lineupPosition ?? 99)
    }
    const av = a.probabilities[sortCol] ?? 0
    const bv = b.probabilities[sortCol] ?? 0
    return sortDir === 'desc' ? bv - av : av - bv
  })

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-white/10">
            {showOrder && (
              <th
                className={cn(
                  'px-2 py-2 text-right cursor-pointer select-none w-8 transition-colors max-md:sticky max-md:left-0 max-md:z-10 max-md:bg-[#0e1015]',
                  microLabel,
                  sortCol === 'lineup' ? 'text-cyan-400' : 'hover:text-zinc-300',
                )}
                onClick={() => onSort('lineup')}
                title="Batting order"
              >
                #
              </th>
            )}
            <th
              className={cn(
                'px-2 py-2 text-left max-md:sticky max-md:z-10 max-md:bg-[#0e1015]',
                showOrder ? 'max-md:left-8' : 'max-md:left-0',
                microLabel,
              )}
            >
              Player
            </th>
            <th className={cn('px-2 py-2 text-right', microLabel)}>xPA</th>
            <ColHeader col="hit1plus" label="P(H≥1)" sortCol={sortCol} sortDir={sortDir} onSort={onSort} />
            <ColHeader col="hit2plus" label="P(H≥2)" sortCol={sortCol} sortDir={sortDir} onSort={onSort} />
            <ColHeader col="hr" label="P(HR)" sortCol={sortCol} sortDir={sortDir} onSort={onSort} />
            <ColHeader col="k1plus" label="P(K)" sortCol={sortCol} sortDir={sortDir} onSort={onSort} />
            <th className={cn('px-2 py-2 text-right', microLabel)}>xH</th>
            <th className={cn('px-2 py-2 text-right', microLabel)}>xTB</th>
          </tr>
        </thead>
        <tbody>
          {sorted.map((b) => {
            const p = b.probabilities
            const a = b.adjustments
            const isOpen = expanded === b.player.id
            return (
              <Fragment key={b.player.id}>
              <tr
                className={cn(
                  'border-b border-white/5 cursor-pointer transition-colors',
                  isOpen ? 'bg-white/[0.03]' : 'hover:bg-white/[0.03]',
                )}
                onClick={() => setExpanded(isOpen ? null : b.player.id)}
              >
                {showOrder && (
                  <td
                    className={cn(
                      'px-2 py-2 text-right font-mono tabular-nums text-zinc-500 max-md:sticky max-md:left-0 max-md:z-10',
                      isOpen ? 'max-md:bg-[#13151b]' : 'max-md:bg-[#0e1015]',
                    )}
                  >
                    {b.lineupPosition ?? '—'}
                  </td>
                )}
                <td
                  className={cn(
                    'px-2 py-2 max-md:sticky max-md:z-10',
                    showOrder ? 'max-md:left-8' : 'max-md:left-0',
                    isOpen ? 'max-md:bg-[#13151b]' : 'max-md:bg-[#0e1015]',
                  )}
                >
                  <div className="flex items-baseline gap-1.5">
                    <Link
                      href={`/players/${b.player.id}`}
                      className="font-medium text-zinc-100 hover:text-cyan-400 transition-colors"
                      onClick={(e) => e.stopPropagation()}
                    >
                      {b.player.name}
                    </Link>
                    <span className="text-xs text-zinc-500">
                      {b.player.bats && `(${b.player.bats})`}
                      {b.player.position && ` · ${b.player.position}`}
                    </span>
                  </div>
                  <div
                    className="mt-0.5 inline-flex items-center gap-1 text-zinc-500 hover:text-cyan-400 transition-colors"
                    title="Click row for pitch-type matchup"
                  >
                    {isOpen ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                    <span className={microLabel}>Pitch matchup</span>
                  </div>
                  <div
                    className="mt-0.5 text-[10px] font-mono tabular-nums text-zinc-500"
                    title={matchupNote(b) || undefined}
                  >
                    {adjHint(b)}
                  </div>
                </td>
                <td className="px-2 py-2 text-right font-mono tabular-nums text-zinc-400">
                  {fixed2(b.expectedPa)}
                </td>
                <td
                  className={cn('px-2 py-2 text-right font-mono tabular-nums', hitClass(p.hit1plus))}
                  title={[adjTooltip(p.hit1plus, a, false, b.pitcherDataQuality), matchupNote(b)]
                    .filter(Boolean)
                    .join('\n')}
                >
                  {pct(p.hit1plus)}
                </td>
                <td
                  className="px-2 py-2 text-right font-mono tabular-nums text-zinc-300"
                  title={adjTooltip(p.hit2plus, a, false, b.pitcherDataQuality)}
                >
                  {pct(p.hit2plus)}
                </td>
                <td
                  className={cn('px-2 py-2 text-right font-mono tabular-nums', hrClass(p.hr))}
                  title={adjTooltip(p.hr, a, true, b.pitcherDataQuality)}
                >
                  {pct(p.hr)}
                </td>
                <td
                  className={cn('px-2 py-2 text-right font-mono tabular-nums', kClass(p.k1plus))}
                  title={adjTooltip(p.k1plus, a, false, b.pitcherDataQuality)}
                >
                  {pct(p.k1plus)}
                </td>
                <td className="px-2 py-2 text-right font-mono tabular-nums text-zinc-400">
                  {fixed2(b.expectedHits)}
                </td>
                <td className="px-2 py-2 text-right font-mono tabular-nums text-zinc-400">
                  {fixed2(b.expectedTotalBases)}
                </td>
              </tr>
              {isOpen && (
                <tr>
                  <td colSpan={colSpan} className="p-0">
                    <ArsenalDetail b={b} />
                  </td>
                </tr>
              )}
              </Fragment>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────────────

export function GameDetail({ gameId }: { gameId: number }) {
  // null = no explicit user choice yet; the effective column then defaults to
  // batting order when a lineup is confirmed, else most-likely outcomes.
  const [sortCol, setSortCol] = useState<SortCol | null>(null)
  const [sortDir, setSortDir] = useState<'asc' | 'desc'>('desc')

  const { data, isPending, isError } = useQuery({
    queryKey: ['game', 'projections', gameId],
    queryFn: () => api.gameProjections(gameId),
  })

  // also fetch today's games to show header info
  const { data: games } = useQuery({
    queryKey: ['games', 'today'],
    queryFn: api.todayGames,
  })
  const game = games?.find((g) => g.gameId === gameId)

  if (isPending) return <div className="p-8 text-zinc-400">Loading projections…</div>
  if (isError) return <div className="p-8 text-rose-400">Failed to load projections.</div>

  const bothConfirmed = data.home.lineupConfirmed && data.away.lineupConfirmed
  const anyConfirmed = data.home.lineupConfirmed || data.away.lineupConfirmed
  const effectiveSortCol: SortCol = sortCol ?? (anyConfirmed ? 'lineup' : 'hit1plus')

  function handleSort(col: SortCol) {
    if (col === effectiveSortCol) {
      setSortDir((d) => (d === 'desc' ? 'asc' : 'desc'))
    } else {
      setSortCol(col)
      setSortDir(col === 'lineup' ? 'asc' : 'desc')
    }
  }

  // The outcome-likelihood toggle only makes sense for probability columns, so
  // clicking it switches off the batting-order sort.
  function handleDir(dir: 'asc' | 'desc') {
    if (effectiveSortCol === 'lineup') setSortCol('hit1plus')
    setSortDir(dir)
  }

  // Away batters face the home SP, and vice versa.
  const homeSpHand = data.away.batters[0]?.opposingPitcher.throws ?? null
  const awaySpHand = data.home.batters[0]?.opposingPitcher.throws ?? null

  const homeRuns = game?.projection?.expectedHomeRuns ?? 0
  const awayRuns = game?.projection?.expectedAwayRuns ?? 0
  const total = homeRuns + awayRuns
  const homePct = total > 0 ? (homeRuns / total) * 100 : 50

  return (
    <main className="max-w-7xl mx-auto w-full px-4 py-8">
      {/* breadcrumb back link */}
      <Link
        href="/"
        className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-cyan-400 transition-colors mb-6"
      >
        <ArrowLeft size={14} /> Today&apos;s Board
      </Link>

      {/* header */}
      {game && (
        <div className="mb-8">
          <div className="flex flex-wrap items-center gap-3 mb-3">
            <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">
              {game.away.name} @ {game.home.name}
            </h1>
            {bothConfirmed ? (
              <Chip tone="confirmed">Lineups confirmed</Chip>
            ) : anyConfirmed ? (
              <Chip tone="projected">Lineups partially confirmed</Chip>
            ) : (
              <Chip tone="projected">Projected lineups</Chip>
            )}
          </div>
          <div className="flex flex-wrap gap-2 items-center text-sm text-zinc-400">
            <Chip>{format(parseApiDate(game.startTimeUtc), 'h:mm a · MMMM d, yyyy')}</Chip>
            <Chip>{game.stadium.name}</Chip>
            {game.stadium.isDome && <Chip tone="info">Dome</Chip>}
            {!game.stadium.isDome && game.weather.windDirDeg != null && (
              <Chip>
                {game.weather.tempF}°F ·{' '}
                <ArrowUp
                  size={11}
                  style={{ transform: `rotate(${game.weather.windDirDeg}deg)` }}
                />
                {game.weather.windMph} mph
              </Chip>
            )}
            {game.probables?.away && (
              <Chip>
                <span className={microLabel}>{game.away.abbr} SP</span>
                <span className="text-zinc-200">{game.probables.away.name}</span>
                {awaySpHand && (
                  <span className="text-[10px] font-medium text-zinc-400">
                    {awaySpHand === 'L' ? 'LHP' : 'RHP'}
                  </span>
                )}
              </Chip>
            )}
            {game.probables?.home && (
              <Chip>
                <span className={microLabel}>{game.home.abbr} SP</span>
                <span className="text-zinc-200">{game.probables.home.name}</span>
                {homeSpHand && (
                  <span className="text-[10px] font-medium text-zinc-400">
                    {homeSpHand === 'L' ? 'LHP' : 'RHP'}
                  </span>
                )}
              </Chip>
            )}
          </div>
        </div>
      )}

      {/* expected runs bar */}
      {game?.projection && (
        <div className="mb-8 bg-[#0e1015] border border-white/10 rounded-xl p-5">
          <div className="flex justify-between text-sm mb-2">
            <span className="text-zinc-100 font-medium">
              {game.home.abbr} <span className={microLabel}>home</span>
            </span>
            <span className={microLabel}>Expected Runs</span>
            <span className="text-zinc-100 font-medium">
              {game.away.abbr} <span className={microLabel}>away</span>
            </span>
          </div>
          <div className="flex h-8 rounded overflow-hidden gap-0.5 bg-black/30">
            <div
              className="bg-cyan-500 flex items-center justify-end pr-2 text-[#08090d] text-sm font-bold font-mono tabular-nums"
              style={{ width: `${homePct}%` }}
            >
              {homeRuns.toFixed(2)}
            </div>
            <div
              className="bg-zinc-700 flex items-center justify-start pl-2 text-zinc-100 text-sm font-bold font-mono tabular-nums"
              style={{ width: `${100 - homePct}%` }}
            >
              {awayRuns.toFixed(2)}
            </div>
          </div>
          <div className="text-center text-xs text-zinc-500 mt-2 font-mono tabular-nums">
            Total: {game.projection.expectedTotal.toFixed(2)} R
          </div>
        </div>
      )}

      {/* sportsbook odds + model edge */}
      <OddsPanel
        gameId={gameId}
        homeAbbr={game?.home.abbr ?? data.home.teamAbbr}
        awayAbbr={game?.away.abbr ?? data.away.teamAbbr}
      />

      {/* empty state */}
      {data.home.batters.length === 0 && data.away.batters.length === 0 && (
        <p className="text-amber-300 bg-amber-400/10 border border-amber-400/30 rounded-xl p-4 text-sm">
          Projection pending — probable pitchers or lineups not yet confirmed.
        </p>
      )}

      {/* sort toggle */}
      {(data.home.batters.length > 0 || data.away.batters.length > 0) && (
        <>
          <div className="flex items-center gap-2 mb-4">
            <span className={microLabel}>Sort</span>
            <button
              onClick={() => handleDir('desc')}
              className={cn(
                'text-xs px-3 py-1 rounded border transition-colors',
                effectiveSortCol !== 'lineup' && sortDir === 'desc'
                  ? 'bg-cyan-500/15 text-cyan-300 border-cyan-400/40'
                  : 'bg-white/5 text-zinc-400 border-white/10 hover:text-zinc-200 hover:border-white/20',
              )}
            >
              Most likely outcomes
            </button>
            <button
              onClick={() => handleDir('asc')}
              className={cn(
                'text-xs px-3 py-1 rounded border transition-colors',
                effectiveSortCol !== 'lineup' && sortDir === 'asc'
                  ? 'bg-cyan-500/15 text-cyan-300 border-cyan-400/40'
                  : 'bg-white/5 text-zinc-400 border-white/10 hover:text-zinc-200 hover:border-white/20',
              )}
            >
              Least likely outcomes
            </button>
          </div>

          {/* tables */}
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
            {/* home */}
            <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
                <span className="font-semibold tracking-tight text-zinc-100 text-sm">
                  {game?.home.name ?? data.home.teamAbbr}{' '}
                  <span className={microLabel}>Home</span>
                </span>
                {data.home.lineupConfirmed ? (
                  <Chip tone="confirmed">Confirmed lineup</Chip>
                ) : (
                  <Chip tone="projected">Projected lineup</Chip>
                )}
              </div>
              {data.home.batters.length > 0 ? (
                <BatterTable
                  batters={data.home.batters}
                  sortCol={effectiveSortCol}
                  sortDir={sortDir}
                  onSort={handleSort}
                  showOrder={data.home.lineupConfirmed}
                />
              ) : (
                <p className="px-4 py-6 text-sm text-zinc-500">No projections available.</p>
              )}
            </div>

            {/* away */}
            <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden">
              <div className="px-4 py-3 border-b border-white/10 flex items-center justify-between">
                <span className="font-semibold tracking-tight text-zinc-100 text-sm">
                  {game?.away.name ?? data.away.teamAbbr}{' '}
                  <span className={microLabel}>Away</span>
                </span>
                {data.away.lineupConfirmed ? (
                  <Chip tone="confirmed">Confirmed lineup</Chip>
                ) : (
                  <Chip tone="projected">Projected lineup</Chip>
                )}
              </div>
              {data.away.batters.length > 0 ? (
                <BatterTable
                  batters={data.away.batters}
                  sortCol={effectiveSortCol}
                  sortDir={sortDir}
                  onSort={handleSort}
                  showOrder={data.away.lineupConfirmed}
                />
              ) : (
                <p className="px-4 py-6 text-sm text-zinc-500">No projections available.</p>
              )}
            </div>
          </div>

          <p className="mt-4 flex items-start gap-1.5 text-xs text-zinc-500">
            <Info size={13} className="mt-0.5 shrink-0" />
            <span>
              Each probability is a league base rate scaled by park, opposing-pitcher,
              and weather multipliers — shown as the{' '}
              <span className="font-mono text-zinc-400">Park · Pitcher · Wx</span> line
              under each batter. Hover any cell for the full base → adjusted breakdown.
              Click a row to expand the pitch-by-pitch matchup.
            </span>
          </p>
        </>
      )}
    </main>
  )
}
