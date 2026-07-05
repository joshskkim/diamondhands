import { redirect } from 'next/navigation'

// The MLB slate board was superseded by Today's Board (home); only /mlb/* subroutes remain.
export default function SlatePage() {
  redirect('/')
}
