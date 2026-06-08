'use client'

import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ArrowLeft, ArrowUp, Info } from 'lucide-react'
import Link from 'next/link'
import { useState } from 'react'
import {
  gameOddsQueryOptions,
  gameProjectionsQueryOptions,
  pitcherSkillQueryOptions,
  todayGamesQueryOptions,
} from '@/lib/api'
import { getStadiumByAbbr } from '@/lib/stadiums'
import type { BatterProjection, LineQuote, PropMarket, TeamBatters } from '@/lib/types'
import { cn, parseApiDate } from '@/lib/utils'
import { BattersTab } from '@/components/game/batters-tab'
import { fixed2, hitClass, hrClass, kClass, pct, STAT_INFO } from '@/components/game/batter-stats'
import { GameSelectorBar } from '@/components/game/game-selector-bar'
import { PitcherArsenalCard } from '@/components/game/pitcher-arsenal-card'
import { StadiumDiagram } from '@/components/game/stadium-diagram'
import { Chip, microLabel } from '@/components/game/ui'
import { OddsPanel } from './odds-panel'

type Tab = 'overview' | 'batters' | 'pitchers'

// First batter on a side carries the opposing SP's full arsenal; grab it once.
function spArsenal(side: TeamBatters) {
  return side.batters.find((b) => (b.pitcherArsenal?.length ?? 0) > 0)?.pitcherArsenal ?? []
}

// ── most-likely highlights (Overview) ─────────────────────────────────────────

type Pick = { b: BatterProjection; abbr: string }

function topBy(
  arr: Pick[],
  sel: (b: BatterProjection) => number,
  dir: 'desc' | 'asc' = 'desc',
  minPa = 0,
): Pick | null {
  const f = arr.filter((x) => (x.b.expectedPa ?? 0) >= minPa)
  if (f.length === 0) return null
  return f.reduce((best, x) => {
    const v = sel(x.b)
    const bv = sel(best.b)
    return (dir === 'desc' ? v > bv : v < bv) ? x : best
  })
}

function HighlightTile({
  label,
  stat,
  pick,
  value,
  cls,
}: {
  label: string
  stat: string
  pick: Pick | null
  value: string
  cls: string
}) {
  if (!pick) return null
  return (
    <div className="rounded-lg bg-white/[0.03] border border-white/5 px-3 py-2.5">
      <div className={microLabel}>{label}</div>
      <Link
        href={`/players/${pick.b.player.id}`}
        className="mt-1 block font-medium text-sm text-zinc-100 hover:text-cyan-400 transition-colors truncate"
      >
        {pick.b.player.name}{' '}
        <span className="text-[10px] uppercase tracking-wide text-cyan-400/70">{pick.abbr}</span>
      </Link>
      <div className={cn('mt-0.5 font-mono tabular-nums text-sm', cls)} title={STAT_INFO[stat]}>
        {value}
      </div>
    </div>
  )
}

function MostLikely({ batters }: { batters: Pick[] }) {
  if (batters.length === 0) return null
  const hit = topBy(batters, (b) => b.probabilities.hit1plus, 'desc')
  const hr = topBy(batters, (b) => b.probabilities.hr, 'desc')
  const tb = topBy(batters, (b) => b.expectedTotalBases, 'desc')
  const safe = topBy(batters, (b) => b.probabilities.k1plus, 'asc', 3.5)

  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl p-5">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-lg font-semibold tracking-tight text-zinc-100">Most likely · this game</h2>
        <span className={microLabel}>Model standouts</span>
      </div>
      <div className="grid grid-cols-2 lg:grid-cols-4 gap-3">
        <HighlightTile label="Most likely hit" stat="P(H≥1)" pick={hit} value={pct(hit?.b.probabilities.hit1plus)} cls={hit ? hitClass(hit.b.probabilities.hit1plus) : ''} />
        <HighlightTile label="Best HR shot" stat="P(HR)" pick={hr} value={pct(hr?.b.probabilities.hr)} cls={hr ? hrClass(hr.b.probabilities.hr) : ''} />
        <HighlightTile label="Most total bases" stat="xTB" pick={tb} value={fixed2(tb?.b.expectedTotalBases)} cls="text-zinc-200" />
        <HighlightTile label="Safest contact" stat="P(K)" pick={safe} value={pct(safe?.b.probabilities.k1plus)} cls={safe ? kClass(safe.b.probabilities.k1plus) : ''} />
      </div>
    </div>
  )
}

// ── pitcher props (Pitchers tab) ──────────────────────────────────────────────

const PITCHER_MARKET_LABEL: Record<string, string> = {
  pitcher_k: 'Strikeouts',
  pitcher_outs: 'Outs (IP)',
}

function amer(n: number | null | undefined) {
  if (n == null) return '—'
  return n > 0 ? `+${n}` : `${n}`
}

function PitcherPropsPanel({ gameId }: { gameId: number }) {
  const { data } = useQuery(gameOddsQueryOptions(gameId))
  const props: PropMarket[] = (data?.props ?? []).filter((p) => p.market.startsWith('pitcher'))
  if (props.length === 0) return null

  const cell = (q: LineQuote | null) =>
    q ? (
      <span className="font-mono tabular-nums text-zinc-100">{amer(q.priceAmerican)}</span>
    ) : (
      <span className="text-zinc-600">—</span>
    )

  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden">
      <div className="px-4 py-3 border-b border-white/10 text-sm font-semibold tracking-tight text-zinc-100">
        Pitcher props
      </div>
      <table className="w-full text-sm">
        <thead>
          <tr className={microLabel}>
            <th className="px-3 py-2 text-left font-medium">Pitcher</th>
            <th className="px-3 py-2 text-right font-medium">Over</th>
            <th className="px-3 py-2 text-right font-medium">Under</th>
          </tr>
        </thead>
        <tbody>
          {props.map((p) => (
            <tr key={`${p.player.id}-${p.market}-${p.line}`} className="border-t border-white/5">
              <td className="px-3 py-2">
                <span className="text-zinc-100">{p.player.name}</span>{' '}
                <span className="text-zinc-500 text-xs">
                  {PITCHER_MARKET_LABEL[p.market] ?? p.market} {p.line}
                </span>
              </td>
              <td className="px-3 py-2 text-right">{cell(p.over)}</td>
              <td className="px-3 py-2 text-right">{cell(p.under)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}

// ── main component ────────────────────────────────────────────────────────────

const TABS: { id: Tab; label: string }[] = [
  { id: 'overview', label: 'Overview' },
  { id: 'batters', label: 'Batters' },
  { id: 'pitchers', label: 'Pitchers' },
]

export function GameDetail({ gameId }: { gameId: number }) {
  const [tab, setTab] = useState<Tab>('overview')

  const { data, isPending, isError } = useQuery(gameProjectionsQueryOptions(gameId))
  const { data: games } = useQuery(todayGamesQueryOptions())
  const game = games?.find((g) => g.gameId === gameId)

  // Season splits vs LHB/RHB for each probable starter (enabled once the id is known).
  const { data: awaySkill } = useQuery(pitcherSkillQueryOptions(game?.probables?.away?.id ?? 0))
  const { data: homeSkill } = useQuery(pitcherSkillQueryOptions(game?.probables?.home?.id ?? 0))

  if (isPending) return <div className="p-8 text-zinc-400">Loading projections…</div>
  if (isError) return <div className="p-8 text-rose-400">Failed to load projections.</div>

  const bothConfirmed = data.home.lineupConfirmed && data.away.lineupConfirmed
  const anyConfirmed = data.home.lineupConfirmed || data.away.lineupConfirmed

  // Away batters face the home SP, and vice versa.
  const homeSpHand = data.away.batters[0]?.opposingPitcher.throws ?? null
  const awaySpHand = data.home.batters[0]?.opposingPitcher.throws ?? null

  const homeAbbr = game?.home.abbr ?? data.home.teamAbbr
  const awayAbbr = game?.away.abbr ?? data.away.teamAbbr

  const homeRuns = game?.projection?.expectedHomeRuns ?? 0
  const awayRuns = game?.projection?.expectedAwayRuns ?? 0
  const total = homeRuns + awayRuns
  const homePct = total > 0 ? (homeRuns / total) * 100 : 50

  const hasBatters = data.home.batters.length > 0 || data.away.batters.length > 0
  const stadiumRef = getStadiumByAbbr(homeAbbr)
  const allBatters: Pick[] = [
    ...data.home.batters.map((b) => ({ b, abbr: homeAbbr })),
    ...data.away.batters.map((b) => ({ b, abbr: awayAbbr })),
  ]

  return (
    <main className="max-w-7xl mx-auto w-full px-4 py-8">
      <Link
        href="/"
        className="inline-flex items-center gap-1 text-sm text-zinc-500 hover:text-cyan-400 transition-colors mb-4"
      >
        <ArrowLeft size={14} /> Today&apos;s Board
      </Link>

      <GameSelectorBar activeGameId={gameId} />

      {/* header */}
      {game && (
        <div className="mb-6">
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
                <ArrowUp size={11} style={{ transform: `rotate(${game.weather.windDirDeg}deg)` }} />
                {game.weather.windMph} mph
              </Chip>
            )}
            {game.probables?.away && (
              <Chip>
                <span className={microLabel}>{awayAbbr} SP</span>
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
                <span className={microLabel}>{homeAbbr} SP</span>
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

      {/* tabs */}
      <div className="flex items-center gap-1 mb-6 border-b border-white/10">
        {TABS.map((t) => (
          <button
            key={t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              'px-4 py-2 text-sm font-medium border-b-2 -mb-px transition-colors',
              tab === t.id
                ? 'border-cyan-400 text-cyan-300'
                : 'border-transparent text-zinc-400 hover:text-zinc-200',
            )}
          >
            {t.label}
          </button>
        ))}
      </div>

      {/* ── Overview ─────────────────────────────────────────────────────────── */}
      {tab === 'overview' && (
        <div className="space-y-6">
          <StadiumDiagram
            stadium={stadiumRef}
            stadiumName={game?.stadium.name ?? stadiumRef?.stadiumName ?? 'Ballpark'}
            isDome={game?.stadium.isDome ?? false}
            weather={game?.weather ?? { tempF: null, windMph: null, windDirDeg: null }}
          />

          {game?.projection && (
            <div className="bg-[#0e1015] border border-white/10 rounded-xl p-5">
              <div className="flex justify-between text-sm mb-2">
                <span className="text-zinc-100 font-medium">
                  {homeAbbr} <span className={microLabel}>home</span>
                </span>
                <span className={microLabel}>Expected Runs</span>
                <span className="text-zinc-100 font-medium">
                  {awayAbbr} <span className={microLabel}>away</span>
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

          {hasBatters && <MostLikely batters={allBatters} />}

          <OddsPanel gameId={gameId} homeAbbr={homeAbbr} awayAbbr={awayAbbr} />
        </div>
      )}

      {/* ── Batters ──────────────────────────────────────────────────────────── */}
      {tab === 'batters' && (
        <BattersTab
          key={gameId}
          home={data.home}
          away={data.away}
          homeName={game?.home.name ?? homeAbbr}
          awayName={game?.away.name ?? awayAbbr}
        />
      )}

      {/* ── Pitchers ─────────────────────────────────────────────────────────── */}
      {tab === 'pitchers' && (
        <div className="space-y-6">
          {hasBatters ? (
            <>
              <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
                <PitcherArsenalCard
                  name={game?.probables?.away?.name ?? `${awayAbbr} starter`}
                  throws={awaySpHand}
                  teamAbbr={awayAbbr}
                  arsenal={spArsenal(data.home)}
                  skill={awaySkill}
                />
                <PitcherArsenalCard
                  name={game?.probables?.home?.name ?? `${homeAbbr} starter`}
                  throws={homeSpHand}
                  teamAbbr={homeAbbr}
                  arsenal={spArsenal(data.away)}
                  skill={homeSkill}
                />
              </div>
              <PitcherPropsPanel gameId={gameId} />
              <p className="flex items-start gap-1.5 text-xs text-zinc-500">
                <Info size={13} className="mt-0.5 shrink-0" />
                <span>
                  Usage bars show each starter&apos;s pitch mix; League xwOBA is the baseline hitters
                  post against that pitch. Per-pitch velocity, whiff%, and vs-LHB/RHB splits light up
                  once the pitcher-stats API lands.
                </span>
              </p>
            </>
          ) : (
            <p className="text-amber-300 bg-amber-400/10 border border-amber-400/30 rounded-xl p-4 text-sm">
              Probable pitchers not yet confirmed.
            </p>
          )}
        </div>
      )}
    </main>
  )
}
