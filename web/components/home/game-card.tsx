'use client'

import { format } from 'date-fns'
import { ArrowUp } from 'lucide-react'
import Link from 'next/link'
import type { TodayGame, Weather } from '@/lib/types'
import { cn, parseApiDate } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

function degreesToCardinal(deg: number): string {
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
  return dirs[Math.round(deg / 45) % 8]
}

function WeatherChip({ weather, isDome }: { weather: Weather; isDome: boolean }) {
  if (isDome) {
    return (
      <span className="inline-flex items-center gap-1 text-[11px] rounded px-1.5 py-0.5 text-cyan-300 border border-cyan-400/30 bg-cyan-400/10">
        Dome — climate controlled
      </span>
    )
  }
  if (!weather.tempF || weather.windMph == null || weather.windDirDeg == null) {
    return <span className="text-[11px] text-zinc-600">Weather TBD</span>
  }
  const from = degreesToCardinal(weather.windDirDeg)
  const to = degreesToCardinal((weather.windDirDeg + 180) % 360)
  return (
    <span className="inline-flex items-center gap-1 text-[11px] text-zinc-400 bg-white/5 border border-white/10 rounded px-1.5 py-0.5">
      {weather.tempF}°F
      <span className="mx-0.5 text-zinc-600">·</span>
      <ArrowUp
        size={11}
        className="inline-block shrink-0"
        style={{ transform: `rotate(${weather.windDirDeg}deg)` }}
      />
      {weather.windMph} mph {from}→{to}
    </span>
  )
}

export function GameCard({ game }: { game: TodayGame }) {
  const localTime = format(parseApiDate(game.startTimeUtc), 'h:mm a')
  const proj = game.projection
  const homeRuns = proj?.expectedHomeRuns ?? 0
  const awayRuns = proj?.expectedAwayRuns ?? 0
  const total = homeRuns + awayRuns
  const homePct = total > 0 ? (homeRuns / total) * 100 : 50

  return (
    <Link
      href={`/mlb/games/${game.gameId}`}
      className="block bg-[#0e1015] border border-white/10 rounded-xl p-5 hover:border-cyan-400/40 hover:shadow-[0_0_0_1px_rgba(34,211,238,0.15)] transition-colors"
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-xl font-bold tracking-tight text-zinc-100">
          {game.away.abbr} <span className="text-zinc-600 font-normal">@</span> {game.home.abbr}
        </span>
        <span className="text-sm text-zinc-500 font-mono tabular-nums">{localTime}</span>
      </div>
      <div className="text-xs text-zinc-500 mb-3 truncate">
        {game.away.name} @ {game.home.name}
      </div>

      <div className="flex items-center gap-2 mb-3 flex-wrap">
        <span className="text-sm text-zinc-400">{game.stadium.name}</span>
        <WeatherChip weather={game.weather} isDome={game.stadium.isDome} />
      </div>

      {proj ? (
        <>
          <div className="flex items-end justify-between mb-2">
            <div>
              <div className="text-3xl font-bold font-mono tabular-nums text-zinc-100">
                {proj.expectedTotal?.toFixed(2)}
                <span className="text-base font-normal text-zinc-500 ml-1">R</span>
              </div>
              <div className={cn(microLabel, 'mt-0.5')}>Projected total</div>
            </div>
            <div className="text-right text-xs text-zinc-500">
              <span className="font-mono tabular-nums text-zinc-300">
                {game.home.abbr} {homeRuns.toFixed(2)}
              </span>
              <span className="mx-1 text-zinc-600">·</span>
              <span className="font-mono tabular-nums text-zinc-300">
                {game.away.abbr} {awayRuns.toFixed(2)}
              </span>
            </div>
          </div>
          <div className="flex h-1.5 rounded overflow-hidden gap-0.5 bg-black/40">
            <div className="bg-cyan-500" style={{ width: `${homePct}%` }} />
            <div className="bg-zinc-700" style={{ width: `${100 - homePct}%` }} />
          </div>
        </>
      ) : (
        <p className="text-xs text-amber-300 bg-amber-400/10 border border-amber-400/30 rounded px-2 py-1.5">
          Projection pending — probable pitchers or lineups not yet confirmed.
        </p>
      )}
    </Link>
  )
}
