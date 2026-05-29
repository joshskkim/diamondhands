'use client'

import { useQuery } from '@tanstack/react-query'
import { format } from 'date-fns'
import { ArrowUp } from 'lucide-react'
import Link from 'next/link'
import { api } from '@/lib/api'
import type { TodayGame, Weather } from '@/lib/types'
import { parseApiDate } from '@/lib/utils'

function degreesToCardinal(deg: number): string {
  const dirs = ['N', 'NE', 'E', 'SE', 'S', 'SW', 'W', 'NW']
  return dirs[Math.round(deg / 45) % 8]
}

function WeatherChip({ weather, isDome }: { weather: Weather; isDome: boolean }) {
  if (isDome) {
    return (
      <span className="text-xs text-zinc-500 bg-zinc-100 rounded px-2 py-0.5">
        🏟 Dome — climate controlled
      </span>
    )
  }
  if (!weather.tempF || weather.windMph == null || weather.windDirDeg == null) {
    return <span className="text-xs text-zinc-400">Weather TBD</span>
  }
  const from = degreesToCardinal(weather.windDirDeg)
  const to = degreesToCardinal((weather.windDirDeg + 180) % 360)
  return (
    <span className="inline-flex items-center gap-1 text-xs text-zinc-600 bg-zinc-100 rounded px-2 py-0.5">
      {weather.tempF}°F
      <span className="mx-1">·</span>
      <ArrowUp
        size={12}
        className="inline-block shrink-0"
        style={{ transform: `rotate(${weather.windDirDeg}deg)` }}
      />
      {weather.windMph} mph {from}→{to}
    </span>
  )
}

function GameCard({ game }: { game: TodayGame }) {
  const localTime = format(parseApiDate(game.startTimeUtc), 'h:mm a')

  return (
    <Link
      href={`/games/${game.gameId}`}
      className="block bg-white border border-zinc-200 rounded-xl p-5 hover:border-zinc-400 hover:shadow-sm transition-all"
    >
      <div className="flex items-center justify-between mb-1">
        <span className="text-xl font-bold tracking-tight">
          {game.away.abbr}{' '}
          <span className="text-zinc-400 font-normal">@</span>{' '}
          {game.home.abbr}
        </span>
        <span className="text-sm text-zinc-500">{localTime}</span>
      </div>
      <div className="text-xs text-zinc-400 mb-3">
        {game.away.name} @ {game.home.name}
      </div>

      <div className="flex items-center gap-2 mb-2">
        <span className="text-sm text-zinc-600">{game.stadium.name}</span>
        {game.stadium.isDome && (
          <span className="text-xs bg-blue-50 text-blue-600 border border-blue-200 rounded px-1.5">
            Dome
          </span>
        )}
      </div>

      <div className="mb-4">
        <WeatherChip weather={game.weather} isDome={game.stadium.isDome} />
      </div>

      {game.projection ? (
        <div className="flex items-end justify-between">
          <div>
            <div className="text-3xl font-bold tabular-nums">
              {game.projection.expectedTotal.toFixed(2)}
              <span className="text-base font-normal text-zinc-400 ml-1">R</span>
            </div>
            <div className="text-xs text-zinc-400 mt-0.5">
              {game.home.abbr} {game.projection.expectedHomeRuns.toFixed(2)} · {game.away.abbr}{' '}
              {game.projection.expectedAwayRuns.toFixed(2)}
            </div>
          </div>
          <div className="text-xs text-zinc-400 text-right">
            Projected at{' '}
            {format(parseApiDate(game.projection.projectedAt), 'h:mm a')}
          </div>
        </div>
      ) : (
        <p className="text-xs text-amber-600 bg-amber-50 rounded px-2 py-1.5">
          Projection pending — probable pitchers or lineups not yet confirmed.
        </p>
      )}
    </Link>
  )
}

export default function SlatePage() {
  const today = format(new Date(), 'MMMM d, yyyy')
  const { data: games, isPending, isError } = useQuery({
    queryKey: ['games', 'today'],
    queryFn: api.todayGames,
  })

  return (
    <main className="max-w-5xl mx-auto w-full px-4 py-8">
      <div className="mb-6">
        <h1 className="text-2xl font-bold">Diamond</h1>
        <p className="text-zinc-500 text-sm mt-0.5">{today}</p>
      </div>

      {isPending && <div className="text-zinc-400 text-sm">Loading slate…</div>}
      {isError && (
        <div className="text-red-500 text-sm">Failed to load games. Is the API running?</div>
      )}
      {games && games.length === 0 && (
        <p className="text-zinc-500">No games today.</p>
      )}
      {games && games.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {games.map((game) => (
            <GameCard key={game.gameId} game={game} />
          ))}
        </div>
      )}
    </main>
  )
}
