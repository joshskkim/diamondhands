import type { Metadata } from 'next'
import { TennisMatchDetail } from './match-detail'

export const metadata: Metadata = { title: 'Match projection' }

export default async function TennisMatchPage({
  params,
}: {
  params: Promise<{ matchId: string }>
}) {
  const { matchId } = await params
  return <TennisMatchDetail matchId={Number(matchId)} />
}
