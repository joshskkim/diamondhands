import { redirect } from 'next/navigation'

// The accuracy charts now live inside the unified Model Report Card. Keep this URL
// alive (bookmarks, old links) by redirecting to the calibration section there.
export default function AccuracyPage() {
  redirect('/mlb/report-card')
}
