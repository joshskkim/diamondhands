'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { ArrowLeft } from 'lucide-react'
import { tennisMatchDetailQueryOptions, type TennisMatchDetail as Detail } from '@/lib/tennis-api'
import { cn } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

function pct(v: number | null | undefined, digits = 0): string {
  return v == null ? '—' : (v * 100).toFixed(digits) + '%'
}
function amer(n: number | null): string {
  return n == null ? '—' : n > 0 ? `+${n}` : `${n}`
}
function num(v: number | null | undefined, digits = 1): string {
  return v == null ? '—' : v.toFixed(digits)
}

function Stat({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2">
      <div className={microLabel}>{label}</div>
      <div className="mt-0.5 font-mono text-sm text-zinc-100">{value}</div>
    </div>
  )
}

function Content({ d }: { d: Detail }) {
  const aWin = d.pWinA
  const bWin = aWin == null ? null : 1 - aWin
  const bestBySide = (side: string) =>
    d.quotes.filter((q) => q.side === side).sort((x, y) => y.priceDecimal - x.priceDecimal)[0]

  return (
    <div className="space-y-5">
      <div className="flex items-center gap-2">
        {d.surface && <span className="rounded-md border border-white/10 bg-white/5 px-1.5 py-0.5 text-[10px] capitalize text-zinc-300">{d.surface}</span>}
        <span className="text-[10px] text-zinc-500">Best of {d.bestOf ?? 3}</span>
        <span className="text-[10px] text-zinc-600">·</span>
        <span className="text-[10px] text-zinc-500 capitalize">{d.status}</span>
      </div>

      {/* matchup header */}
      <div className="grid grid-cols-2 gap-3">
        {[{ p: d.playerA, win: aWin, elo: d.eloA }, { p: d.playerB, win: bWin, elo: d.eloB }].map((s, i) => (
          <div key={i} className="rounded-xl border border-white/10 bg-[#0e1015] p-4">
            <div className="text-base font-semibold text-zinc-100">{s.p.name}</div>
            {s.p.country && <div className="text-[10px] text-zinc-500">{s.p.country}</div>}
            <div className="mt-2 font-mono text-2xl text-cyan-400">{pct(s.win)}</div>
            <div className={microLabel}>win prob</div>
            <div className="mt-2 text-xs text-zinc-500">Elo {num(s.elo, 0)}</div>
          </div>
        ))}
      </div>

      {/* projection stats */}
      <div>
        <p className={microLabel}>Projection</p>
        <div className="mt-2 grid grid-cols-2 gap-2 sm:grid-cols-4">
          <Stat label="Serve win A" value={pct(d.pServeA, 1)} />
          <Stat label="Serve win B" value={pct(d.pServeB, 1)} />
          <Stat label="Total games" value={num(d.expTotalGames, 1)} />
          <Stat label="Straight sets" value={pct(d.probStraightSets, 0)} />
        </div>
      </div>

      {/* best play */}
      {d.bestPlay && d.bestPlay.edgePct > 0 && (
        <div className="rounded-xl border border-emerald-400/20 bg-emerald-400/[0.04] p-4">
          <p className={microLabel}>Model&apos;s best play</p>
          <div className="mt-1 flex items-center justify-between">
            <span className="text-sm font-semibold text-zinc-100">{d.bestPlay.playerName}</span>
            <span className="font-mono text-sm text-zinc-300">
              {amer(d.bestPlay.priceAmerican)} @ {d.bestPlay.bookmaker}
            </span>
          </div>
          <div className="mt-1 flex gap-4 text-xs text-zinc-400">
            <span>model <span className="font-mono text-zinc-200">{pct(d.bestPlay.modelProb, 1)}</span></span>
            <span>fair <span className="font-mono text-zinc-200">{pct(d.bestPlay.fairProb, 1)}</span></span>
            <span>edge <span className="font-mono font-semibold text-emerald-400">+{d.bestPlay.edgePct.toFixed(1)}%</span></span>
            <span>EV <span className={cn('font-mono', d.bestPlay.evPct > 0 ? 'text-emerald-300' : 'text-zinc-500')}>{d.bestPlay.evPct > 0 ? '+' : ''}{d.bestPlay.evPct.toFixed(1)}%</span></span>
          </div>
        </div>
      )}

      {/* odds */}
      {d.quotes.length > 0 && (
        <div>
          <p className={microLabel}>Best line</p>
          <div className="mt-2 grid grid-cols-2 gap-2">
            {[{ p: d.playerA, side: 'player_a' }, { p: d.playerB, side: 'player_b' }].map(({ p, side }) => {
              const q = bestBySide(side)
              return (
                <div key={side} className="rounded-lg border border-white/10 bg-white/[0.02] px-3 py-2">
                  <div className="truncate text-xs text-zinc-300">{p.name}</div>
                  <div className="mt-0.5 font-mono text-sm text-zinc-100">
                    {q ? amer(q.priceAmerican) : '—'}
                    {q && <span className="ml-1 text-[10px] text-zinc-500">{q.bookmaker}</span>}
                  </div>
                </div>
              )
            })}
          </div>
        </div>
      )}
    </div>
  )
}

export function TennisMatchDetail({ matchId }: { matchId: number }) {
  const { data, isLoading, isError } = useQuery(tennisMatchDetailQueryOptions(matchId))

  return (
    <main className="mx-auto w-full max-w-2xl px-4 py-8">
      <Link href="/tennis/matches" className="inline-flex items-center gap-1 text-sm text-zinc-400 hover:text-cyan-400">
        <ArrowLeft className="h-4 w-4" /> Matches
      </Link>
      <div className="mt-4">
        {isLoading && <p className="text-sm text-zinc-500">Loading…</p>}
        {isError && <p className="text-sm text-rose-400">Couldn&apos;t load this match.</p>}
        {data && <Content d={data} />}
      </div>
    </main>
  )
}
