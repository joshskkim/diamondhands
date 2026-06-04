import type { Metadata } from 'next'
import { BestBetsBoard } from './best-bets-board'

export const metadata: Metadata = { title: 'Best Bets' }

export default function BestBetsPage() {
  return <BestBetsBoard />
}
