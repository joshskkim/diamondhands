'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { tennisMatchesQueryOptions, type TennisMatch } from '@/lib/tennis-api'
import { cn } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

const SURFACE_TONE: Record<string, string> = {
  hard: 'text-sky-300 border-sky-400/30 bg-sky-400/10',
  clay: 'text-orange-300 border-orange-400/30 bg-orange-400/10',
  grass: 'text-emerald-300 border-emerald-400/30 bg-emerald-400/10',
}

function pct(v: number | null | undefined): string {
  return v == null ? '—' : Math.round(v * 100) + '%'
}

function amer(n: number | null): string {
  if (n == null) return ''
  return n > 0 ? `+${n}` : `${n}`
}

function startLabel(iso: string | null): string {
  if (!iso) return ''
  const d = new Date(iso.replace(' ', 'T'))
  if (Number.isNaN(d.getTime())) return ''
  return d.toLocaleString(undefined, { weekday: 'short', hour: 'numeric', minute: '2-digit' })
}

function MatchCard({ m }: { m: TennisMatch }) {
  const aWin = m.pWinA
  const bWin = aWin == null ? null : 1 - aWin
  const aFav = aWin != null && aWin >= 0.5
  const best = m.bestPlay

  return (
    <Link
      href={`/tennis/matches/${m.matchId}`}
      className="block rounded-xl border border-white/10 bg-[#0e1015] p-4 transition-colors hover:border-cyan-400/40 hover:shadow-[0_0_0_1px_rgba(34,211,238,0.15)]"
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          {m.surface && (
            <span className={cn('rounded-md border px-1.5 py-0.5 text-[10px] font-medium capitalize',
              SURFACE_TONE[m.surface] ?? 'text-zinc-300 border-white/10 bg-white/5')}>
              {m.surface}
            </span>
          )}
          <span className="text-[10px] text-zinc-500">Bo{m.bestOf ?? 3}</span>
        </div>
        <span className="text-[10px] text-zinc-500">{startLabel(m.startTimeUtc)}</span>
      </div>

      <div className="mt-3 space-y-1.5">
        <PlayerRow name={m.playerA.name} country={m.playerA.country} win={aWin} fav={aFav} />
        <PlayerRow name={m.playerB.name} country={m.playerB.country} win={bWin} fav={aWin != null && !aFav} />
      </div>

      {best && best.edgePct > 0 && (
        <div className="mt-3 flex items-center justify-between border-t border-white/10 pt-2">
          <span className={microLabel}>Model edge</span>
          <span className="text-xs text-zinc-300">
            <span className="font-medium text-zinc-100">{best.playerName}</span>{' '}
            <span className="font-mono text-zinc-400">{amer(best.priceAmerican)}</span>{' '}
            <span className="font-mono font-semibold text-emerald-400">+{best.edgePct.toFixed(1)}%</span>
            <span className={cn('ml-1 font-mono', best.evPct > 0 ? 'text-emerald-300' : 'text-zinc-500')}>
              (EV {best.evPct > 0 ? '+' : ''}{best.evPct.toFixed(1)}%)
            </span>
          </span>
        </div>
      )}
    </Link>
  )
}

function PlayerRow({
  name, country, win, fav,
}: { name: string; country: string | null; win: number | null; fav: boolean }) {
  return (
    <div className="flex items-center justify-between">
      <span className={cn('text-sm', fav ? 'font-semibold text-zinc-100' : 'text-zinc-300')}>
        {name}
        {country && <span className="ml-1.5 text-[10px] text-zinc-600">{country}</span>}
      </span>
      <span className={cn('font-mono text-sm tabular-nums', fav ? 'text-cyan-400' : 'text-zinc-400')}>
        {pct(win)}
      </span>
    </div>
  )
}

export function TennisMatchBoard() {
  const { data, isLoading, isError } = useQuery(tennisMatchesQueryOptions())

  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8">
      <p className={microLabel}>ATP · Model edges</p>
      <h1 className="mt-1 text-3xl text-zinc-100">Matches</h1>
      <p className="mt-2 max-w-xl text-sm text-zinc-400">
        Surface-blended Elo win probabilities with the model&apos;s best match-winner
        value vs the books.
      </p>

      <div className="mt-6 space-y-3">
        {isLoading && <p className="text-sm text-zinc-500">Loading slate…</p>}
        {isError && <p className="text-sm text-rose-400">Couldn&apos;t load matches.</p>}
        {data && data.length === 0 && (
          <p className="text-sm text-zinc-500">No matches on the board right now.</p>
        )}
        {data?.map((m) => <MatchCard key={m.matchId} m={m} />)}
      </div>
    </main>
  )
}
