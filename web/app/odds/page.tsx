import type { Metadata } from 'next'
import { OddsBoard } from './odds-board'

export const metadata: Metadata = { title: 'Best Lines' }

export default function OddsBoardPage() {
  return <OddsBoard />
}
