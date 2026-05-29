import { PlayerDetail } from './player-detail'

export default async function PlayerPage({
  params,
}: {
  params: Promise<{ playerId: string }>
}) {
  const { playerId } = await params
  return <PlayerDetail playerId={Number(playerId)} />
}
