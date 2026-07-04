import { Suspense } from 'react'
import { PlayerCompare } from './player-compare'

export const metadata = {
  title: 'Compare Players — Diamond',
  description: 'Stack batters side by side on recent form: counting stats, per-PA rates, and xwOBA trend.',
}

export default function ComparePage() {
  return (
    <Suspense>
      <PlayerCompare />
    </Suspense>
  )
}
