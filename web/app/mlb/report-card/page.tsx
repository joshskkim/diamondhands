import type { Metadata } from 'next'
import { ReportCard } from './report-card'

export const metadata: Metadata = { title: 'Model Report Card' }

export default function ReportCardPage() {
  return <ReportCard />
}
