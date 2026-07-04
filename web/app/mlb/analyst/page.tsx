import type { Metadata } from 'next'
import { AgentPanel } from '@/components/agent-panel'

export const metadata: Metadata = { title: 'Diamond Analyst' }

/**
 * The Diamond Analyst: a stateful, authenticated co-pilot. Ask for a pick and it runs a
 * bull-vs-skeptic debate, sizes the bet to your bankroll, and (with your confirmation) saves it
 * to a tracker that gets graded against real results + CLV.
 */
export default function AnalystPage() {
  return (
    <div className="px-4 py-8">
      <div className="mx-auto max-w-2xl pb-5">
        <h1 className="text-lg font-semibold text-zinc-100">Diamond Analyst</h1>
        <p className="pt-1 text-sm text-zinc-400">
          Your personal betting co-pilot. It debates a pick (bull vs. skeptic), sizes it to your
          bankroll, and — only with your confirmation — saves it to a tracker graded against real
          results and CLV.
        </p>
      </div>
      <AgentPanel />
    </div>
  )
}
