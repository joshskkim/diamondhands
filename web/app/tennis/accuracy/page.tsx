import type { Metadata } from 'next'
import { TennisAccuracyBoard } from './accuracy-board'

export const metadata: Metadata = { title: 'Tennis Accuracy' }

export default function TennisAccuracyPage() {
  return <TennisAccuracyBoard />
}
