'use client'

import { useState } from 'react'
import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { gameOddsQueryOptions } from '@/lib/api'
import type { LineQuote, PropMarket } from '@/lib/types'
import { cn } from '@/lib/utils'
import { microLabel } from '@/components/ui/primitives'
import { Chip, Stat } from '@/components/game/ui'
import { pct, signed, signedPct } from '@/lib/format'
import {
  BATTER_PROP_MARKETS,
  bookLabel,
  formatAmerican,
  MARKET_LABEL,
  PITCHER_PROP_MARKETS,
} from '@/lib/odds'

// A side clearing +5% EV is a "value" play — the same bar the picks bar uses.
const VALUE_EV = 0.05

/** The better of a prop's two sides by EV, or null when neither is priced by the model. */
function bestEv(p: PropMarket): number | null {
  const evs = [p.over?.evPct, p.under?.evPct].filter((e): e is number => e != null)
  return evs.length ? Math.max(...evs) : null
}

// Model edge on one side = our probability minus the de-vigged market probability.
// Null for markets we don't model (pitcher props carry no modelProb).
function edgeOf(q: LineQuote | null | undefined): number | null {
  if (!q || q.modelProb == null || q.fairProb == null) return null
  return q.modelProb - q.fairProb
}

// EV is the headline edge number: warm green when the model beats the price, muted
// when it's a wash, rose when the price is against us.
function evClass(ev: number | null | undefined) {
  if (ev == null) return 'text-zinc-500'
  if (ev > 0.05) return 'text-emerald-400'
  if (ev > 0) return 'text-emerald-300'
  if (ev > -0.05) return 'text-zinc-400'
  return 'text-rose-300'
}

function edgeClass(e: number | null | undefined) {
  if (e == null) return 'text-zinc-500'
  if (e > 0.02) return 'text-emerald-400'
  if (e > 0) return 'text-emerald-300'
  if (e > -0.02) return 'text-zinc-400'
  return 'text-rose-300'
}

// A card gets the cyan "value" treatment when its best side clears +5% EV, so genuine
// edges pop out of the grid.
function valueCard(ev: number | null | undefined) {
  return ev != null && ev > VALUE_EV
    ? 'border-cyan-400/30 bg-gradient-to-br from-cyan-500/10 to-[#0e1015]'
    : 'border-white/10 bg-[#0e1015]'
}

function gameSelectionLabel(market: string, q: LineQuote, homeAbbr: string, awayAbbr: string) {
  const team = q.side === 'home' ? homeAbbr : awayAbbr
  if (market === 'moneyline') return team
  if (market === 'run_line') return `${team} ${signed(q.line, 1)}`
  if (market === 'total') return `${q.side === 'over' ? 'Over' : 'Under'} ${q.line}`
  return q.side
}

/** One game-market selection (e.g. moneyline home) as a card with a Model/Fair/Edge/EV grid. */
function GameQuoteCard({
  market,
  q,
  homeAbbr,
  awayAbbr,
}: {
  market: string
  q: LineQuote
  homeAbbr: string
  awayAbbr: string
}) {
  const edge = edgeOf(q)
  return (
    <div className={cn('rounded-xl border px-4 py-3 flex flex-col gap-2.5', valueCard(q.evPct))}>
      <div className="flex items-center gap-2">
        <Chip tone="info">{MARKET_LABEL[market] ?? market}</Chip>
        {q.bestBook && (
          <span className="ml-auto font-mono text-[11px] text-zinc-500">{bookLabel(q.bestBook)}</span>
        )}
      </div>
      <div className="flex items-baseline justify-between gap-3">
        <span className="text-sm font-bold tracking-tight text-zinc-100">
          {gameSelectionLabel(market, q, homeAbbr, awayAbbr)}
        </span>
        <span className="shrink-0 font-mono tabular-nums text-sm text-zinc-100">
          {formatAmerican(q.priceAmerican)}
        </span>
      </div>
      <div className="grid grid-cols-4 gap-2">
        <Stat label="Model" value={pct(q.modelProb)} className="text-zinc-200" />
        <Stat label="Fair" value={pct(q.fairProb)} className="text-zinc-400" />
        <Stat label="Edge" value={signedPct(edge)} className={edgeClass(edge)} />
        <Stat label="EV" value={signedPct(q.evPct)} className={evClass(q.evPct)} />
      </div>
    </div>
  )
}

/** One side (Over / Under) of a player prop: price + book on the left, model view on the right. */
function PropSideRow({ label, q }: { label: string; q: LineQuote | null }) {
  if (!q) {
    return (
      <div className="flex items-center gap-2 rounded-lg bg-white/[0.02] px-2.5 py-2">
        <Chip tone="neutral" className="shrink-0 font-medium">
          {label}
        </Chip>
        <span className="ml-auto text-sm text-zinc-600">—</span>
      </div>
    )
  }
  // Model/EV only exist when we can price this line (see OddsService.propOverProb): an
  // unmodeled side — off-canonical line, no projection, no sim/workload row — carries a
  // real book price but no model. Drop the Model/EV cells there rather than show blanks
  // that read as broken; Fair (de-vigged market) stands alone when it's the only signal.
  const modeled = q.modelProb != null
  return (
    <div className="flex items-center gap-2 rounded-lg bg-white/[0.02] px-2.5 py-2">
      <Chip tone="neutral" className="shrink-0 font-medium">
        {label}
      </Chip>
      <span className="font-mono tabular-nums text-sm text-zinc-100">{formatAmerican(q.priceAmerican)}</span>
      {q.bestBook && <span className="text-[11px] text-zinc-500">{bookLabel(q.bestBook)}</span>}
      <div className="ml-auto flex items-center gap-3">
        {modeled && <Stat label="Model" value={pct(q.modelProb)} className="text-zinc-300" />}
        {q.fairProb != null && <Stat label="Fair" value={pct(q.fairProb)} className="text-zinc-400" />}
        {modeled && <Stat label="EV" value={signedPct(q.evPct)} className={evClass(q.evPct)} />}
      </div>
    </div>
  )
}

/** One player-prop card: player + line header, then the Over and Under rows. The market
 *  isn't repeated on the card — the selected market in the sidebar already names it. */
function PropCard({ p }: { p: PropMarket }) {
  const isPitcher = p.market.startsWith('pitcher')
  const lineLabel =
    p.market === 'pitcher_outs' && p.line != null
      ? `${p.line} (${(p.line / 3).toFixed(1)} IP)`
      : p.line
  return (
    <div className={cn('rounded-xl border px-4 py-3 flex flex-col gap-2.5', valueCard(bestEv(p)))}>
      <div className="flex items-baseline justify-between gap-2">
        <Link
          href={`/mlb/players/${p.player.id}`}
          className="text-sm font-bold tracking-tight text-zinc-100 hover:text-cyan-300 transition-colors"
        >
          {p.player.name}
        </Link>
        <Chip tone={isPitcher ? 'projected' : 'info'} className="shrink-0">
          {lineLabel}
        </Chip>
      </div>
      <div className="flex flex-col gap-1.5">
        <PropSideRow label="Over" q={p.over} />
        <PropSideRow label="Under" q={p.under} />
      </div>
    </div>
  )
}

/** The market picker: a Batters/Pitchers toggle over the list of markets that actually
 *  have quotes for this game. A dot marks markets holding at least one +5% EV side. */
function PropMarketList({
  markets,
  byMarket,
  active,
  onSelect,
}: {
  markets: readonly string[]
  byMarket: Map<string, PropMarket[]>
  active: string
  onSelect: (market: string) => void
}) {
  return (
    <div className="flex gap-1.5 overflow-x-auto pb-1 lg:flex-col lg:overflow-visible lg:pb-0">
      {markets.map((m) => {
        const props = byMarket.get(m) ?? []
        const hasValue = props.some((p) => (bestEv(p) ?? 0) > VALUE_EV)
        return (
          <button
            key={m}
            onClick={() => onSelect(m)}
            className={cn(
              'flex shrink-0 items-center gap-2 rounded border px-3 py-1.5 text-xs transition-colors lg:shrink',
              active === m
                ? 'bg-cyan-500/15 text-cyan-300 border-cyan-400/40'
                : 'bg-white/5 text-zinc-400 border-white/10 hover:text-zinc-200 hover:border-white/20',
            )}
          >
            {hasValue && <span className="size-1.5 shrink-0 rounded-full bg-emerald-400" />}
            <span className="whitespace-nowrap">{MARKET_LABEL[m] ?? m}</span>
            <span className="ml-auto pl-1 font-mono tabular-nums text-[11px] text-zinc-500">
              {props.length}
            </span>
          </button>
        )
      })}
    </div>
  )
}

/** Player props, one market at a time: pick a side of the ball, then a market. */
function PropsSection({ props }: { props: PropMarket[] }) {
  const [side, setSide] = useState<'batters' | 'pitchers'>('batters')
  const [selected, setSelected] = useState<string | null>(null)

  const byMarket = new Map<string, PropMarket[]>()
  for (const p of props) {
    const list = byMarket.get(p.market)
    if (list) list.push(p)
    else byMarket.set(p.market, [p])
  }

  const order: readonly string[] = side === 'batters' ? BATTER_PROP_MARKETS : PITCHER_PROP_MARKETS
  const markets = order.filter((m) => byMarket.has(m))
  // Derive rather than sync: flipping the toggle can't strand a selection from the
  // other side of the ball, and no effect is needed to reset it.
  const active = selected && markets.includes(selected) ? selected : markets[0]

  // Edges first — the SQL orders by player name, which buries them.
  const shown = [...(byMarket.get(active) ?? [])].sort(
    (a, b) => (bestEv(b) ?? -Infinity) - (bestEv(a) ?? -Infinity),
  )

  return (
    <section>
      <h3 className="text-sm font-semibold text-zinc-300 mb-2.5">Player props</h3>
      <div className="grid gap-4 lg:grid-cols-[190px_1fr]">
        <div className="flex flex-col gap-2">
          <div className="flex items-center gap-2">
            {(['batters', 'pitchers'] as const).map((s) => (
              <button
                key={s}
                onClick={() => {
                  setSide(s)
                  setSelected(null)
                }}
                className={cn(
                  'flex-1 rounded border px-3 py-1.5 text-xs capitalize transition-colors',
                  side === s
                    ? 'bg-cyan-500/15 text-cyan-300 border-cyan-400/40'
                    : 'bg-white/5 text-zinc-400 border-white/10 hover:text-zinc-200 hover:border-white/20',
                )}
              >
                {s}
              </button>
            ))}
          </div>
          {markets.length > 0 && (
            <PropMarketList
              markets={markets}
              byMarket={byMarket}
              active={active}
              onSelect={setSelected}
            />
          )}
        </div>

        {markets.length > 0 ? (
          <div className="grid grid-cols-1 xl:grid-cols-2 gap-3 content-start">
            {shown.map((p) => (
              <PropCard key={`${p.player.id}-${p.market}-${p.line}`} p={p} />
            ))}
          </div>
        ) : (
          <p className="text-sm text-zinc-500">No {side.slice(0, -1)} props for this game.</p>
        )}
      </div>
    </section>
  )
}

export function OddsPanel({
  gameId,
  homeAbbr,
  awayAbbr,
}: {
  gameId: number
  homeAbbr: string
  awayAbbr: string
}) {
  const { data, isPending, isError } = useQuery(gameOddsQueryOptions(gameId))

  if (isPending || isError) return null // odds are supplemental; fail quietly
  if (!data.hasOdds) {
    return (
      <div className="mb-8 bg-[#0e1015] border border-white/10 rounded-xl p-5">
        <h2 className="text-sm font-semibold tracking-tight text-zinc-100 mb-1">Odds &amp; Edges</h2>
        <p className="text-sm text-zinc-500">
          No sportsbook odds loaded for this game. Run{' '}
          <span className="font-mono text-zinc-400">refresh-odds</span> (needs{' '}
          <span className="font-mono text-zinc-400">ODDS_API_KEY</span>, or{' '}
          <span className="font-mono text-zinc-400">--sample</span>).
        </p>
      </div>
    )
  }

  return (
    <div className="mb-8">
      <div className="flex items-baseline justify-between mb-3">
        <h2 className="text-lg font-semibold tracking-tight text-zinc-100">Odds &amp; Edges</h2>
        <span className={microLabel}>Fair = no-vig line · EV = model vs. best price</span>
      </div>

      <div className="space-y-6">
        <section>
          <h3 className="text-sm font-semibold text-zinc-300 mb-2.5">Game markets</h3>
          {data.game.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {data.game.flatMap((m) =>
                m.quotes.map((q) => (
                  <GameQuoteCard
                    key={`${m.market}-${q.side}-${q.line}`}
                    market={m.market}
                    q={q}
                    homeAbbr={homeAbbr}
                    awayAbbr={awayAbbr}
                  />
                )),
              )}
            </div>
          ) : (
            <p className="text-sm text-zinc-500">No game markets.</p>
          )}
        </section>

        {data.props.length > 0 ? (
          <PropsSection props={data.props} />
        ) : (
          <section>
            <h3 className="text-sm font-semibold text-zinc-300 mb-2.5">Player props</h3>
            <p className="text-sm text-zinc-500">No player props.</p>
          </section>
        )}
      </div>
    </div>
  )
}
