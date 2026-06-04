import { User } from 'lucide-react'
import { ComingSoon } from '@/components/coming-soon'

export const metadata = { title: 'Profile' }

export default function ProfilePage() {
  return (
    <ComingSoon
      icon={<User size={26} strokeWidth={1.75} />}
      title="Your Profile"
      description="Personalized picks, saved bets, and settings will live here — coming soon."
    />
  )
}
