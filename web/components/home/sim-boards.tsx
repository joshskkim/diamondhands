'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { mostLikelyQueryOptions } from '@/lib/api'
import type { MostLikely } from '@/lib/types'
import { cn } from '@/lib/utils'
import { BoardCard, Rank } from './pick-boards'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

// Concise by design: top N leans per market, strongest first. The full slate
// lives on the game pages — this is the skim view.
const N = 5

function pct(v: number | null | undefined) {
  if (v == null) return '—'
  return (v * 100).toFixed(0) + '%'
}

function signed(v: number | null | undefined, digits = 1) {
  if (v == null) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(digits)
}

function Matchup({ gameId, label }: { gameId: number; label: string }) {
  return (
    <Link
      href={`/mlb/games/${gameId}`}
      className="font-mono text-[13px] text-zinc-200 hover:text-white transition-colors"
    >
      {label}
    </Link>
  )
}

function Empty() {
  return <div className="px-4 py-6 text-xs text-zinc-600">Nothing simulated for this slate yet.</div>
}

function TotalsCard({ data }: { data: MostLikely['totals'] }) {
  const rows = [...data]
    .sort((a, b) => Math.abs(b.edge ?? 0) - Math.abs(a.edge ?? 0))
    .slice(0, N)
  return (
    <BoardCard
      title="Totals vs Line"
      blurb="Sim expected total vs the consensus book line — strongest leans first"
    >
      {rows.length === 0 && <Empty />}
      {rows.map((t, i) => (
        <div key={t.gameId} className="flex items-center gap-3 px-4 py-2 hover:bg-white/[0.03] transition-colors">
          <Rank n={i + 1} />
          <div className="min-w-0 flex-1">
            <Matchup gameId={t.gameId} label={t.matchup} />
            <div className="text-[11px] text-zinc-500 mt-0.5">
              sim <span className="text-zinc-300 font-mono">{t.simTotal.toFixed(1)}</span>
              {t.bookLine != null && (
                <> · line <span className="text-zinc-400 font-mono">{t.bookLine.toFixed(1)}</span></>
              )}
            </div>
          </div>
          <div className="text-right shrink-0 w-14">
            <div className={microLabel}>Edge</div>
            <div
              className={cn(
                'text-[13px] font-mono tabular-nums',
                t.edge == null ? 'text-zinc-600' : t.edge > 0 ? 'text-emerald-400' : t.edge < 0 ? 'text-rose-400' : 'text-zinc-400',
              )}
            >
              {t.edge == null ? '—' : signed(t.edge)}
            </div>
          </div>
          <div className="text-right shrink-0 w-12">
            <div className={microLabel}>Over</div>
            <div className="text-[13px] font-mono tabular-nums text-zinc-300">{pct(t.pOver)}</div>
          </div>
        </div>
      ))}
    </BoardCard>
  )
}

function F5Card({ data }: { data: MostLikely['f5'] }) {
  const rows = data.slice(0, N)
  return (
    <BoardCard
      title="First 5 Innings"
      blurb="The starter-driven period the sim predicts best — F5 total + the moneyline lean"
    >
      {rows.length === 0 && <Empty />}
      {rows.map((f, i) => (
        <div key={f.gameId} className="flex items-center gap-3 px-4 py-2 hover:bg-white/[0.03] transition-colors">
          <Rank n={i + 1} />
          <div className="min-w-0 flex-1">
            <Matchup gameId={f.gameId} label={f.matchup} />
            <div className="text-[11px] text-zinc-500 mt-0.5">
              F5 lean <span className="text-zinc-300 font-semibold">{f.favorite}</span>{' '}
              {pct(f.favoriteProb)} · tie {pct(f.pTie)}
            </div>
          </div>
          <div className="text-right shrink-0 w-14">
            <div className={microLabel}>F5 Tot</div>
            <div className="text-[13px] font-mono tabular-nums text-zinc-300">{f.f5Total.toFixed(1)}</div>
          </div>
          <div className="text-right shrink-0 w-12">
            <div className={microLabel}>Edge</div>
            <div
              className={cn(
                'text-[13px] font-mono tabular-nums',
                f.edge == null ? 'text-zinc-600' : f.edge > 0 ? 'text-emerald-400' : 'text-rose-400',
              )}
            >
              {f.edge == null ? '—' : signed(f.edge)}
            </div>
          </div>
        </div>
      ))}
    </BoardCard>
  )
}

function NrfiCard({ data }: { data: MostLikely['nrfi'] }) {
  const rows = data.slice(0, N)
  return (
    <BoardCard title="NRFI / YRFI" blurb="First-inning run lean by simulated confidence">
      {rows.length === 0 && <Empty />}
      {rows.map((n, i) => (
        <div key={n.gameId} className="flex items-center gap-3 px-4 py-2 hover:bg-white/[0.03] transition-colors">
          <Rank n={i + 1} />
          <div className="min-w-0 flex-1">
            <Matchup gameId={n.gameId} label={n.matchup} />
            <div className="text-[11px] text-zinc-500 mt-0.5">
              YRFI {pct(n.pYrfi)} · NRFI {pct(n.pNrfi)}
            </div>
          </div>
          <div className="text-right shrink-0 w-16">
            <div className={microLabel}>Lean</div>
            <div
              className={cn(
                'text-[13px] font-semibold tabular-nums',
                n.lean === 'NRFI' ? 'text-sky-400' : 'text-amber-400',
              )}
            >
              {n.lean} {pct(n.leanProb)}
            </div>
          </div>
        </div>
      ))}
    </BoardCard>
  )
}

/**
 * The game-sim leans that used to live on the standalone Most Likely page,
 * condensed into one section of Today's Board. Renders nothing until the sim
 * has produced output for the slate.
 */
export function SimBoards() {
  const { data } = useQuery(mostLikelyQueryOptions())

  if (!data) return null
  if (data.totals.length === 0 && data.f5.length === 0 && data.nrfi.length === 0) return null

  return (
    <section className="mb-10">
      <h2 className="text-sm font-semibold tracking-tight text-zinc-100 mb-1">
        Sim Signals
      </h2>
      <p className="text-zinc-500 text-xs mb-3">
        Monte-Carlo game-simulator leans — totals vs the book line, first five innings, and
        first-inning runs. Top {N} per market.
      </p>
      <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <TotalsCard data={data.totals} />
        <F5Card data={data.f5} />
        <NrfiCard data={data.nrfi} />
      </div>
    </section>
  )
}
