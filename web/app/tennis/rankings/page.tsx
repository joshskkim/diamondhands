import type { Metadata } from 'next'
import { TennisRankingsBoard } from './rankings-board'

export const metadata: Metadata = { title: 'Tennis Rankings' }

export default function TennisRankingsPage() {
  return <TennisRankingsBoard />
}
