import { redirect } from 'next/navigation'

// The Most Likely board now lives on Today's Board (home).
export default function MostLikelyPage() {
  redirect('/')
}
