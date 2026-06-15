import type { Metadata } from 'next'
import Link from 'next/link'
import { Calendar, BarChart3 } from 'lucide-react'

export const metadata: Metadata = { title: 'Tennis' }

const cards = [
  { href: '/tennis/matches', label: 'Matches', icon: Calendar,
    desc: 'Surface-blended Elo win probabilities and the model’s best match-winner value.' },
  { href: '/tennis/rankings', label: 'Rankings', icon: BarChart3,
    desc: 'Player Elo by surface (overall, hard, clay, grass) with serve strength.' },
]

export default function TennisPage() {
  return (
    <main className="mx-auto w-full max-w-3xl px-4 py-8">
      <p className="text-[10px] font-medium uppercase tracking-[0.12em] text-zinc-500">ATP</p>
      <h1 className="mt-1 text-3xl text-zinc-100">Tennis</h1>
      <p className="mt-2 max-w-xl text-sm text-zinc-400">
        Match projections from a surface-blended Elo + point-by-point model, with
        model edges vs the books.
      </p>

      <div className="mt-6 grid gap-3 sm:grid-cols-2">
        {cards.map((c) => {
          const Icon = c.icon
          return (
            <Link
              key={c.href}
              href={c.href}
              className="rounded-xl border border-white/10 bg-[#0e1015] p-5 transition-colors hover:border-cyan-400/40"
            >
              <Icon className="h-5 w-5 text-cyan-400" />
              <div className="mt-2 text-base font-semibold text-zinc-100">{c.label}</div>
              <p className="mt-1 text-sm text-zinc-400">{c.desc}</p>
            </Link>
          )
        })}
      </div>
    </main>
  )
}
