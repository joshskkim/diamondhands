import { LineChart } from 'lucide-react'
import { ComingSoon } from '@/components/coming-soon'

export const metadata = { title: 'Bet Trackers' }

export default function TrackersPage() {
  return (
    <ComingSoon
      icon={<LineChart size={26} strokeWidth={1.75} />}
      title="Bet Trackers"
      description="Track your bets, ROI, and CLV across MLB and tennis — coming soon."
    />
  )
}
