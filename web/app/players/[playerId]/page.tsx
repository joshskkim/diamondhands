import type { Metadata } from 'next'
import { fetchPlayer } from '@/lib/api'
import { PlayerDetail } from './player-detail'

export async function generateMetadata({
  params,
}: {
  params: Promise<{ playerId: string }>
}): Promise<Metadata> {
  const { playerId } = await params
  try {
    const player = await fetchPlayer(Number(playerId))
    return { title: player.fullName }
  } catch {
    return { title: 'Player' }
  }
}

export default async function PlayerPage({
  params,
}: {
  params: Promise<{ playerId: string }>
}) {
  const { playerId } = await params
  return <PlayerDetail playerId={Number(playerId)} />
}
