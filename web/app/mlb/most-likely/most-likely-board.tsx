'use client'

import Link from 'next/link'
import { useQuery } from '@tanstack/react-query'
import { mostLikelyQueryOptions } from '@/lib/api'
import type { MostLikely, PropLeader } from '@/lib/types'
import { cn } from '@/lib/utils'

const microLabel = 'text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium'

function pct(v: number | null | undefined) {
  if (v == null) return '—'
  return (v * 100).toFixed(0) + '%'
}

function signed(v: number | null | undefined, digits = 1) {
  if (v == null) return '—'
  return (v > 0 ? '+' : '') + v.toFixed(digits)
}

// ── card shell ────────────────────────────────────────────────────────────────

function BoardCard({
  title,
  blurb,
  children,
}: {
  title: string
  blurb: string
  children: React.ReactNode
}) {
  return (
    <div className="bg-[#0e1015] border border-white/10 rounded-xl overflow-hidden flex flex-col">
      <div className="px-4 pt-4 pb-3 border-b border-white/10">
        <h2 className="font-semibold tracking-tight text-zinc-100 text-sm">{title}</h2>
        <p className="text-xs text-zinc-500 mt-0.5">{blurb}</p>
      </div>
      <div className="divide-y divide-white/5">{children}</div>
    </div>
  )
}

function Rank({ n }: { n: number }) {
  return (
    <span className="w-5 shrink-0 text-right font-mono tabular-nums text-xs text-zinc-600">
      {n}
    </span>
  )
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

// ── totals vs line ──────────────────────────────────────────────────────────

function TotalsCard({ data }: { data: MostLikely['totals'] }) {
  return (
    <BoardCard
      title="Totals vs Line"
      blurb="Sim expected total vs the consensus book line — biggest overs first, unders last"
    >
      {data.length === 0 && <Empty />}
      {data.map((t, i) => (
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

// ── first five innings ──────────────────────────────────────────────────────

function F5Card({ data }: { data: MostLikely['f5'] }) {
  return (
    <BoardCard
      title="First 5 Innings"
      blurb="The starter-driven period the sim predicts best — F5 total + the moneyline lean"
    >
      {data.length === 0 && <Empty />}
      {data.map((f, i) => (
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

// ── NRFI / YRFI ─────────────────────────────────────────────────────────────

function NrfiCard({ data }: { data: MostLikely['nrfi'] }) {
  return (
    <BoardCard title="NRFI / YRFI" blurb="First-inning run lean by simulated confidence">
      {data.length === 0 && <Empty />}
      {data.map((n, i) => (
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

// ── prop leaderboards ───────────────────────────────────────────────────────

function PropCard({
  title,
  blurb,
  rows,
  format,
}: {
  title: string
  blurb: string
  rows: PropLeader[]
  format: (v: number) => string
}) {
  return (
    <BoardCard title={title} blurb={blurb}>
      {rows.length === 0 && <Empty />}
      {rows.map((r, i) => (
        <div key={r.playerId} className="flex items-center gap-3 px-4 py-2 hover:bg-white/[0.03] transition-colors">
          <Rank n={i + 1} />
          <div className="min-w-0 flex-1">
            <Link
              href={`/mlb/players/${r.playerId}`}
              className="text-[13px] text-zinc-200 hover:text-white transition-colors truncate block"
            >
              {r.player}
            </Link>
            <div className="text-[11px] text-zinc-500 mt-0.5">
              {r.team} · {r.matchup}
            </div>
          </div>
          <div className="text-right shrink-0 w-12 text-[13px] font-mono tabular-nums text-emerald-400">
            {format(r.value)}
          </div>
        </div>
      ))}
    </BoardCard>
  )
}

function Empty() {
  return <div className="px-4 py-6 text-xs text-zinc-600">Nothing projected for this slate yet.</div>
}

// ── board ───────────────────────────────────────────────────────────────────

export function MostLikelyBoard() {
  const { data, isLoading, isError } = useQuery(mostLikelyQueryOptions())

  return (
    <div className="mx-auto max-w-6xl px-4 py-8">
      <header className="mb-6">
        <h1 className="text-2xl font-semibold tracking-tight text-zinc-100">Most Likely</h1>
        <p className="text-sm text-zinc-500 mt-1">
          Headline picks from the Monte-Carlo game simulator
          {data?.date ? ` · ${data.date}` : ''}
        </p>
      </header>

      {isLoading && <div className="text-sm text-zinc-500">Simulating…</div>}
      {isError && <div className="text-sm text-rose-400">Could not load the board.</div>}

      {data && (
        <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
          <TotalsCard data={data.totals} />
          <F5Card data={data.f5} />
          <NrfiCard data={data.nrfi} />
          <PropCard
            title="Most Likely — Hit"
            blurb="P(≥1 hit) across the slate"
            rows={data.props.hits}
            format={pct}
          />
          <PropCard
            title="Most Likely — Home Run"
            blurb="P(≥1 HR) across the slate"
            rows={data.props.homeRuns}
            format={pct}
          />
          <PropCard
            title="Most Total Bases"
            blurb="Expected total bases"
            rows={data.props.totalBases}
            format={(v) => v.toFixed(2)}
          />
          <PropCard
            title="Most Likely — Strikeout"
            blurb="P(≥1 batter strikeout)"
            rows={data.props.strikeouts}
            format={pct}
          />
        </div>
      )}
    </div>
  )
}
