import { GameDetail } from './game-detail'

export default async function GamePage({
  params,
}: {
  params: Promise<{ gameId: string }>
}) {
  const { gameId } = await params
  return <GameDetail gameId={Number(gameId)} />
}
