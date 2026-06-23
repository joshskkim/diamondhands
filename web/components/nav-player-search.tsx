'use client'

import { useRouter } from 'next/navigation'
import { PlayerSearch } from '@/components/player-search'

/**
 * The global player search shown in the nav. Thin wrapper over PlayerSearch that
 * routes to the chosen player's page. `onNavigate` lets the mobile drawer close
 * itself when a result is picked.
 */
export function NavPlayerSearch({ onNavigate }: { onNavigate?: () => void }) {
  const router = useRouter()
  return (
    <PlayerSearch
      placeholder="Search players…"
      onSelect={(p) => {
        router.push(`/mlb/players/${p.id}`)
        onNavigate?.()
      }}
    />
  )
}
