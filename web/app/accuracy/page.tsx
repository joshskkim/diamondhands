import type { Metadata } from 'next'
import { AccuracyBoard } from './accuracy-board'

export const metadata: Metadata = { title: 'Accuracy' }

export default function AccuracyPage() {
  return <AccuracyBoard />
}
