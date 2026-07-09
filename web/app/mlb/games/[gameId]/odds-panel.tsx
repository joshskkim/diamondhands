'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { gameOddsQueryOptions } from '@/lib/api'
import type { LineQuote, PropMarket } from '@/lib/types'
import { cn } from '@/lib/utils'
import { microLabel } from '@/components/ui/primitives'
import { Chip, Stat } from '@/components/game/ui'
import { pct, signed, signedPct } from '@/lib/format'
import { bookLabel, formatAmerican, MARKET_LABEL } from '@/lib/odds'

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

// A card gets the cyan "value" treatment when its best side clears +5% EV — the same
// threshold the picks bar uses, so genuine edges pop out of the grid.
function valueCard(bestEv: number | null | undefined) {
  return bestEv != null && bestEv > 0.05
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
  return (
    <div className="flex items-center gap-2 rounded-lg bg-white/[0.02] px-2.5 py-2">
      <Chip tone="neutral" className="shrink-0 font-medium">
        {label}
      </Chip>
      <span className="font-mono tabular-nums text-sm text-zinc-100">{formatAmerican(q.priceAmerican)}</span>
      {q.bestBook && <span className="text-[11px] text-zinc-500">{bookLabel(q.bestBook)}</span>}
      <div className="ml-auto flex items-center gap-3">
        <Stat label="Model" value={pct(q.modelProb)} className="text-zinc-300" />
        <Stat label="Fair" value={pct(q.fairProb)} className="text-zinc-400" />
        <Stat label="EV" value={signedPct(q.evPct)} className={evClass(q.evPct)} />
      </div>
    </div>
  )
}

/** One player-prop card: player + market/line header, then the Over and Under rows. */
function PropCard({ p }: { p: PropMarket }) {
  const isPitcher = p.market.startsWith('pitcher')
  const bestEv = Math.max(p.over?.evPct ?? -1, p.under?.evPct ?? -1)
  const lineLabel =
    p.market === 'pitcher_outs' && p.line != null
      ? `${p.line} (${(p.line / 3).toFixed(1)} IP)`
      : p.line
  return (
    <div className={cn('rounded-xl border px-4 py-3 flex flex-col gap-2.5', valueCard(bestEv))}>
      <div className="flex items-baseline justify-between gap-2">
        <Link
          href={`/mlb/players/${p.player.id}`}
          className="text-sm font-bold tracking-tight text-zinc-100 hover:text-cyan-300 transition-colors"
        >
          {p.player.name}
        </Link>
        <Chip tone={isPitcher ? 'projected' : 'info'} className="shrink-0">
          {MARKET_LABEL[p.market] ?? p.market} {lineLabel}
        </Chip>
      </div>
      <div className="flex flex-col gap-1.5">
        <PropSideRow label="Over" q={p.over} />
        <PropSideRow label="Under" q={p.under} />
      </div>
    </div>
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

        <section>
          <h3 className="text-sm font-semibold text-zinc-300 mb-2.5">Player props</h3>
          {data.props.length > 0 ? (
            <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-3 gap-3">
              {data.props.map((p) => (
                <PropCard key={`${p.player.id}-${p.market}-${p.line}`} p={p} />
              ))}
            </div>
          ) : (
            <p className="text-sm text-zinc-500">No player props.</p>
          )}
        </section>
      </div>
    </div>
  )
}
