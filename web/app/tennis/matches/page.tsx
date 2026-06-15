import type { Metadata } from 'next'
import { TennisMatchBoard } from './match-board'

export const metadata: Metadata = { title: 'Tennis Matches' }

export default function TennisMatchesPage() {
  return <TennisMatchBoard />
}
