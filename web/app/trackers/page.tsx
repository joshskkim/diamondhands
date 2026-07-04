import type { Metadata } from 'next'
import { TrackerView } from './tracker-view'

export const metadata: Metadata = { title: 'Tracker' }

/**
 * The personal Tracker — the picks you've tailed + bets you've logged, graded with your own
 * ROI/CLV (the personal mirror of the model's Report Card).
 */
export default function TrackersPage() {
  return (
    <div className="px-4 py-8">
      <div className="mx-auto max-w-4xl">
        <div className="pb-5">
          <h1 className="text-lg font-semibold text-zinc-100">Tracker</h1>
          <p className="pt-1 text-sm text-zinc-400">
            Your tailed picks and logged bets, graded with your own ROI and closing-line value.
          </p>
        </div>
        <TrackerView />
      </div>
    </div>
  )
}
