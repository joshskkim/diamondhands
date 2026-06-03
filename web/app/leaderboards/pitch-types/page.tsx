import type { Metadata } from 'next'
import { PitchTypeLeaderboard } from './pitch-type-leaderboard'

export const metadata: Metadata = { title: 'Pitch Matchups' }

export default function PitchTypeLeaderboardPage() {
  return <PitchTypeLeaderboard />
}
