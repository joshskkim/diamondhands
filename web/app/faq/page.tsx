import type { Metadata } from 'next'
import Link from 'next/link'
import { cn } from '@/lib/utils'
import { microLabel } from '@/components/ui/primitives'

export const metadata: Metadata = { title: 'FAQ' }

const card = 'bg-[#0e1015] border border-white/10 rounded-xl p-4'

// The Fair / Model / Edge / EV glossary that used to live at the bottom of the
// Best Lines board. Definitions mirror how the API computes them (OddsService).
const GLOSSARY: {
  term: string
  what: string
  calc: string
  direction: string
  dirClass: string
}[] = [
  {
    term: 'Fair',
    what: "The market's probability with the bookmaker's vig (margin) removed — the honest market consensus.",
    calc: "this side's implied % ÷ both sides' implied %",
    direction: 'Reference point, not a bet signal.',
    dirClass: 'text-zinc-500',
  },
  {
    term: 'Model',
    what: 'Our projection’s probability the bet hits. Blank for markets we don’t model (e.g. strikeouts).',
    calc: 'Poisson run model (game lines) or batter projections (hit/HR)',
    direction: 'Higher = we like it more.',
    dirClass: 'text-emerald-400/80',
  },
  {
    term: 'Edge',
    what: 'How much more likely we think the outcome is than the vig-free market. What the Best Lines board is ranked by.',
    calc: 'Model − Fair',
    direction: 'Higher is better; positive means we see value the market doesn’t.',
    dirClass: 'text-emerald-400/80',
  },
  {
    term: 'EV',
    what: 'Expected return per $1 staked at the best price. Measured against the price you’d actually pay (vig included), so it can read lower than Edge.',
    calc: 'Model × decimal odds − 1',
    direction: 'Higher is better; +5% ≈ 5¢ profit per $1 long-run.',
    dirClass: 'text-emerald-400/80',
  },
]

// One blurb per destination, so newcomers know what each tab is for.
const TABS: { name: string; href: string; blurb: string }[] = [
  {
    name: "Today's Board",
    href: '/',
    blurb:
      "The day's games plus the model's curated top picks and most-likely props — each with a short reason for why it stands out.",
  },
  {
    name: 'Best Lines',
    href: '/mlb/odds',
    blurb:
      'The best available price for every market across the books, ranked by our model’s edge over the vig-free market. (See the metrics above.)',
  },
  {
    name: 'Pitch Matchups',
    href: '/mlb/leaderboards/pitch-types',
    blurb:
      'How each pitcher’s arsenal stacks up against hitters, pitch type by pitch type — who has the platoon and pitch-mix advantage.',
  },
  {
    name: 'Accuracy',
    href: '/mlb/report-card',
    blurb: 'How the model’s past projections have actually scored, so you can judge how much to trust today’s numbers.',
  },
  {
    name: 'Leaderboards',
    href: '/leaderboard',
    blurb: 'Standings and rankings across the app’s tracked metrics.',
  },
]

export default function FaqPage() {
  return (
    <main className="max-w-3xl mx-auto w-full px-4 py-8">
      <div className={microLabel}>Help</div>
      <h1 className="text-2xl font-bold tracking-tight text-zinc-100 mt-1 mb-2">FAQ</h1>
      <p className="text-sm text-zinc-400 mb-6 max-w-2xl">
        How to read the app and what the numbers mean. We’ll add to this as more questions come in.
      </p>

      {/* Reading the numbers */}
      <section className={cn(card, 'mb-6')}>
        <div className={microLabel}>Reading the numbers</div>
        <h2 className="text-lg font-semibold text-zinc-100 mt-1 mb-3">
          Fair · Model · Edge · EV
        </h2>
        <dl className="space-y-3 text-sm">
          {GLOSSARY.map((g) => (
            <div key={g.term} className="grid grid-cols-1 gap-0.5 sm:grid-cols-[5rem_1fr] sm:gap-3">
              <dt className="font-medium text-zinc-200">{g.term}</dt>
              <dd className="text-zinc-400">
                {g.what}
                <span className="block text-zinc-500">
                  <span className={cn(microLabel, 'mr-1.5')}>Calc</span>
                  <span className="font-mono tabular-nums text-zinc-400">{g.calc}</span>
                </span>
                <span className={cn('block mt-0.5 text-xs', g.dirClass)}>{g.direction}</span>
              </dd>
            </div>
          ))}
        </dl>
      </section>

      {/* How to read the app */}
      <section className={card}>
        <div className={microLabel}>How to read the app</div>
        <h2 className="text-lg font-semibold text-zinc-100 mt-1 mb-3">The tabs</h2>
        <dl className="space-y-3 text-sm">
          {TABS.map((t) => (
            <div key={t.href} className="grid grid-cols-1 gap-0.5 sm:grid-cols-[8.5rem_1fr] sm:gap-3">
              <dt>
                <Link href={t.href} className="font-medium text-cyan-400 hover:text-cyan-300">
                  {t.name}
                </Link>
              </dt>
              <dd className="text-zinc-400">{t.blurb}</dd>
            </div>
          ))}
        </dl>
      </section>
    </main>
  )
}
