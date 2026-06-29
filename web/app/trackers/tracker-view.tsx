'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { Check, X, Clock } from 'lucide-react'
import { fetchTracker, queryKeys, type TrackerEntry, type TrackerSummary } from '@/lib/api'
import { useAuth } from '@/components/auth-provider'
import { cn } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'
const card = 'bg-[#0e1015] border border-white/10 rounded-xl p-4'

function pct(v: number | null) {
  return v == null ? '—' : (v * 100).toFixed(1) + '%'
}
function signed(v: number | null, suffix = '') {
  return v == null ? '—' : (v > 0 ? '+' : '') + v.toFixed(suffix === '%' ? 1 : 2) + suffix
}
function amer(v: number | null) {
  return v == null ? '—' : v > 0 ? `+${v}` : `${v}`
}

function StatusBadge({ e }: { e: TrackerEntry }) {
  if (!e.scored) {
    return <span className="inline-flex items-center gap-1 text-zinc-500"><Clock className="h-3.5 w-3.5" /> Pending</span>
  }
  if (e.won === true) {
    return <span className="inline-flex items-center gap-1 text-emerald-400"><Check className="h-3.5 w-3.5" /> Won</span>
  }
  if (e.won === false) {
    return <span className="inline-flex items-center gap-1 text-rose-400"><X className="h-3.5 w-3.5" /> Lost</span>
  }
  return <span className="text-zinc-500">Push</span>
}

function SummaryHeader({ s }: { s: TrackerSummary }) {
  const tiles: { label: string; value: string; cls?: string }[] = [
    { label: 'Record', value: `${s.wins}–${s.losses}${s.pushes ? ` · ${s.pushes}P` : ''}` },
    { label: 'Units', value: signed(s.units), cls: s.units >= 0 ? 'text-emerald-400' : 'text-rose-400' },
    { label: 'ROI', value: signed(s.roiPct, '%'), cls: s.roiPct >= 0 ? 'text-emerald-400' : 'text-rose-400' },
    { label: 'Avg CLV', value: s.avgClv == null ? '—' : signed(s.avgClv * 100, '%'), cls: (s.avgClv ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400' },
  ]
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
      {tiles.map((t) => (
        <div key={t.label} className={card}>
          <p className={microLabel}>{t.label}</p>
          <p className={cn('pt-1 text-xl font-semibold tabular-nums text-zinc-100', t.cls)}>{t.value}</p>
        </div>
      ))}
    </div>
  )
}

function subject(e: TrackerEntry) {
  const who = e.playerName ?? `Game ${e.gameId}`
  const lineStr = e.line != null ? ` ${e.line}` : ''
  return `${who} · ${e.market} ${e.side}${lineStr}`
}

function SignInPrompt() {
  return (
    <div className={cn(card, 'text-center')}>
      <p className="text-sm text-zinc-300">Sign in to track the picks you tail and the bets you log.</p>
      <Link
        href="/signin"
        className="mt-3 inline-block rounded-lg border border-white/15 bg-white/5 px-4 py-2 text-sm font-medium text-zinc-100 hover:bg-white/10"
      >
        Sign in
      </Link>
    </div>
  )
}

export function TrackerView() {
  const { user, isLoading: authLoading } = useAuth()
  const { data, isLoading } = useQuery({
    queryKey: queryKeys.tracker(),
    queryFn: fetchTracker,
    enabled: !!user,
  })

  if (authLoading) return null
  if (!user) return <SignInPrompt />
  if (isLoading) return <p className="text-sm text-zinc-500">Loading your tracker…</p>

  const entries = data?.entries ?? []
  return (
    <div className="space-y-5">
      {data?.summary && <SummaryHeader s={data.summary} />}
      {entries.length === 0 ? (
        <div className={cn(card, 'text-sm text-zinc-400')}>
          Nothing tracked yet. Tail a pick from{' '}
          <Link href="/" className="text-cyan-400 hover:underline">Today&apos;s Board</Link>, or ask the{' '}
          <Link href="/mlb/analyst" className="text-cyan-400 hover:underline">Analyst</Link> to save one.
        </div>
      ) : (
        <div className="overflow-x-auto rounded-xl border border-white/10">
          <table className="w-full text-sm">
            <thead>
              <tr className={microLabel}>
                <th className="px-3 py-2 text-left font-medium">Date</th>
                <th className="px-3 py-2 text-left font-medium">Pick</th>
                <th className="px-3 py-2 text-left font-medium">Src</th>
                <th className="px-3 py-2 text-right font-medium">Price</th>
                <th className="px-3 py-2 text-right font-medium">Stake</th>
                <th className="px-3 py-2 text-right font-medium">Conf</th>
                <th className="px-3 py-2 text-right font-medium">CLV</th>
                <th className="px-3 py-2 text-left font-medium">Result</th>
              </tr>
            </thead>
            <tbody>
              {entries.map((e) => (
                <tr key={`${e.source}-${e.id}`} className="border-t border-white/5">
                  <td className="px-3 py-2 font-mono text-xs text-zinc-500 whitespace-nowrap">{e.slateDate}</td>
                  <td className="px-3 py-2 text-zinc-100">
                    {e.playerId ? (
                      <Link href={`/mlb/players/${e.playerId}`} className="hover:text-cyan-400">{subject(e)}</Link>
                    ) : (
                      <Link href={`/mlb/games/${e.gameId}`} className="hover:text-cyan-400">{subject(e)}</Link>
                    )}
                  </td>
                  <td className="px-3 py-2 text-xs text-zinc-500">{e.source === 'agent' ? 'Tailed' : 'Bet'}</td>
                  <td className="px-3 py-2 text-right font-mono tabular-nums text-zinc-300">
                    {amer(e.priceAmerican)} <span className="text-zinc-600 text-xs">{e.book ?? ''}</span>
                  </td>
                  <td className="px-3 py-2 text-right tabular-nums text-zinc-300">{e.stakeUnits == null ? '—' : `${e.stakeUnits}u`}</td>
                  <td className="px-3 py-2 text-right tabular-nums text-violet-300">{e.confidence == null ? '—' : pct(e.confidence)}</td>
                  <td className={cn('px-3 py-2 text-right tabular-nums', (e.clv ?? 0) >= 0 ? 'text-emerald-400' : 'text-rose-400')}>
                    {e.clv == null ? '—' : signed(e.clv * 100, '%')}
                  </td>
                  <td className="px-3 py-2 whitespace-nowrap"><StatusBadge e={e} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
