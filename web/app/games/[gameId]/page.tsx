import type { Metadata } from 'next'
import { format } from 'date-fns'
import { fetchTodayGames } from '@/lib/api'
import { parseApiDate } from '@/lib/utils'
import { GameDetail } from './game-detail'

export async function generateMetadata({
  params,
}: {
  params: Promise<{ gameId: string }>
}): Promise<Metadata> {
  try {
    const { gameId } = await params
    const games = await fetchTodayGames()
    const game = games.find((g) => g.gameId === Number(gameId))
    if (!game) return { title: 'Game projections' }
    const day = format(parseApiDate(game.startTimeUtc), 'MMM d')
    return { title: `${game.away.name} @ ${game.home.name} — ${day}` }
  } catch {
    return { title: 'Game projections' }
  }
}

export default async function GamePage({
  params,
}: {
  params: Promise<{ gameId: string }>
}) {
  const { gameId } = await params
  return <GameDetail gameId={Number(gameId)} />
}
