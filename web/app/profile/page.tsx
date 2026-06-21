import type { Metadata } from 'next'
import { ProfileView } from './profile-view'

export const metadata: Metadata = { title: 'Profile' }

export default function ProfilePage() {
  return (
    <div className="max-w-6xl mx-auto w-full px-4 py-8">
      <div className="mx-auto max-w-md">
        <div className="bg-[#0e1015] border border-white/10 rounded-xl p-8">
          <div className="text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium">
            Account
          </div>
          <h1 className="text-2xl font-bold tracking-tight text-zinc-100 mt-2 mb-6">
            Your Profile
          </h1>
          <ProfileView />
        </div>
      </div>
    </div>
  )
}
