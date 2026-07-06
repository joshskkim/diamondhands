'use client'

import { useQuery } from '@tanstack/react-query'
import { gameOddsQueryOptions } from '@/lib/api'
import type { GameMarket, LineQuote, PropMarket } from '@/lib/types'
import { cn } from '@/lib/utils'
import { microLabel } from '@/components/ui/primitives'
import { pct, signed } from '@/lib/format'

const MARKET_LABEL: Record<string, string> = {
  moneyline: 'Moneyline',
  run_line: 'Run line',
  total: 'Total',
  hit: 'Hit',
  hr: 'Home run',
  pitcher_k: 'Strikeouts',
  pitcher_outs: 'Outs (IP)',
}

function amer(n: number | null | undefined) {
  if (n == null) return '—'
  return n > 0 ? `+${n}` : `${n}`
}

// EV is the headline edge number: warm green for positive, muted/rose for negative.
function evClass(ev: number | null | undefined) {
  if (ev == null) return 'text-zinc-600'
  if (ev > 0.05) return 'text-emerald-400 font-semibold'
  if (ev > 0) return 'text-emerald-300'
  if (ev > -0.05) return 'text-zinc-400'
  return 'text-rose-300'
}

function evText(ev: number | null | undefined) {
  if (ev == null) return '—'
  return (ev > 0 ? '+' : '') + (ev * 100).toFixed(1) + '%'
}

function gameSelection(market: string, q: LineQuote, homeAbbr: string, awayAbbr: string) {
  const team = q.side === 'home' ? homeAbbr : awayAbbr
  if (market === 'moneyline') return team
  if (market === 'run_line') return `${team} ${signed(q.line, 1)}`
  if (market === 'total') return `${q.side === 'over' ? 'Over' : 'Under'} ${q.line}`
  return q.side
}

function QuoteRow({ label, q }: { label: string; q: LineQuote }) {
  return (
    <tr className="border-t border-white/5">
      <td className="px-3 py-2 text-zinc-200">{label}</td>
      <td className="px-3 py-2 text-right">
        <span className="font-mono tabular-nums text-zinc-100">{amer(q.priceAmerican)}</span>{' '}
        <span className="text-zinc-500 text-xs">{q.bestBook}</span>
      </td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-400">{pct(q.fairProb)}</td>
      <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">{pct(q.modelProb)}</td>
      <td className={cn('px-3 py-2 text-right font-mono tabular-nums', evClass(q.evPct))}>{evText(q.evPct)}</td>
    </tr>
  )
}

function GameMarketsTable({
  markets,
  homeAbbr,
  awayAbbr,
}: {
  markets: GameMarket[]
  homeAbbr: string
  awayAbbr: string
}) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className={microLabel}>
          <th className="px-3 py-2 text-left font-medium">Market</th>
          <th className="px-3 py-2 text-right font-medium">Best line</th>
          <th className="px-3 py-2 text-right font-medium" title="No-vig market probability">Fair</th>
          <th className="px-3 py-2 text-right font-medium">Model</th>
          <th className="px-3 py-2 text-right font-medium">EV</th>
        </tr>
      </thead>
      <tbody>
        {markets.map((m) =>
          m.quotes.map((q) => (
            <QuoteRow
              key={`${m.market}-${q.side}-${q.line}`}
              label={`${MARKET_LABEL[m.market] ?? m.market} · ${gameSelection(m.market, q, homeAbbr, awayAbbr)}`}
              q={q}
            />
          )),
        )}
      </tbody>
    </table>
  )
}

function PropLabel({ p }: { p: PropMarket }) {
  const ip = p.market === 'pitcher_outs' && p.line != null ? ` (${(p.line / 3).toFixed(1)} IP)` : ''
  return (
    <>
      <span className="text-zinc-100">{p.player.name}</span>{' '}
      <span className="text-zinc-500 text-xs">
        {MARKET_LABEL[p.market] ?? p.market} {p.line}
        {ip}
      </span>
    </>
  )
}

/** One over/under price cell: american odds, no-vig fair %, and EV underneath. */
function PropCell({ q }: { q: LineQuote | null }) {
  if (!q) return <td className="px-3 py-2 text-right text-zinc-600">—</td>
  return (
    <td className="px-3 py-2 text-right">
      <div className="font-mono tabular-nums text-zinc-100">{amer(q.priceAmerican)}</div>
      <div className="text-[10px] text-zinc-500">{q.bestBook}</div>
      {q.fairProb != null && (
        <div className="text-[10px] font-mono tabular-nums text-zinc-500" title="No-vig fair probability">
          fair {pct(q.fairProb)}
        </div>
      )}
      <div className={cn('text-xs font-mono tabular-nums', evClass(q.evPct))}>{evText(q.evPct)}</div>
    </td>
  )
}

function PropsTable({ props }: { props: PropMarket[] }) {
  return (
    <table className="w-full text-sm">
      <thead>
        <tr className={microLabel}>
          <th className="px-3 py-2 text-left font-medium">Prop</th>
          <th className="px-3 py-2 text-right font-medium">Over</th>
          <th className="px-3 py-2 text-right font-medium">Under</th>
        </tr>
      </thead>
      <tbody>
        {props.map((p) => (
          <tr key={`${p.player.id}-${p.market}-${p.line}`} className="border-t border-white/5">
            <td className="px-3 py-2">
              <PropLabel p={p} />
            </td>
            <PropCell q={p.over} />
            <PropCell q={p.under} />
          </tr>
        ))}
      </tbody>
    </table>
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
      <div className="grid grid-cols-1 xl:grid-cols-2 gap-6">
        <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-white/10 text-sm font-semibold tracking-tight text-zinc-100">
            Game markets
          </div>
          {data.game.length > 0 ? (
            <GameMarketsTable markets={data.game} homeAbbr={homeAbbr} awayAbbr={awayAbbr} />
          ) : (
            <p className="px-4 py-6 text-sm text-zinc-500">No game markets.</p>
          )}
        </div>
        <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden">
          <div className="px-4 py-3 border-b border-white/10 text-sm font-semibold tracking-tight text-zinc-100">
            Player props
          </div>
          {data.props.length > 0 ? (
            <PropsTable props={data.props} />
          ) : (
            <p className="px-4 py-6 text-sm text-zinc-500">No player props.</p>
          )}
        </div>
      </div>
    </div>
  )
}
