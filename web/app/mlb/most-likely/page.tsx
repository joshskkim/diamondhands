import type { Metadata } from 'next'
import { MostLikelyBoard } from './most-likely-board'

export const metadata: Metadata = { title: 'Most Likely' }

export default function MostLikelyPage() {
  return <MostLikelyBoard />
}
