'use client'

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Sparkles, ArrowRight, Loader2, Check, ShieldQuestion, Swords, Gavel } from 'lucide-react'
import {
  askAgent,
  confirmAction,
  type AgentEvent,
  type AgentConfirm,
  type AskLink,
} from '@/lib/api'
import { cn } from '@/lib/utils'

type RoleTurn = { role: string; text: string }

const ROLE_META: Record<string, { label: string; icon: typeof Swords; cls: string }> = {
  bull: { label: 'Bull', icon: Swords, cls: 'text-emerald-300 border-emerald-400/30' },
  skeptic: { label: 'Skeptic', icon: ShieldQuestion, cls: 'text-amber-300 border-amber-400/30' },
  judge: { label: 'Judge', icon: Gavel, cls: 'text-cyan-300 border-cyan-400/30' },
}

/**
 * The Diamond Analyst panel: the authenticated, stateful co-pilot. Streams the live tool feed,
 * the bull/skeptic/judge debate turns, and any write proposals (which the user must confirm —
 * the model never executes a write itself).
 */
export function AgentPanel() {
  const router = useRouter()
  const abortRef = useRef<AbortController | null>(null)

  const [question, setQuestion] = useState('')
  const [statuses, setStatuses] = useState<string[]>([])
  const [roles, setRoles] = useState<RoleTurn[]>([])
  const [confirms, setConfirms] = useState<AgentConfirm[]>([])
  const [results, setResults] = useState<string[]>([])
  const [links, setLinks] = useState<AskLink[]>([])
  const [answer, setAnswer] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [asked, setAsked] = useState(false)

  async function run(q: string) {
    const trimmed = q.trim()
    if (!trimmed || loading) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setQuestion(trimmed)
    setAsked(true)
    setStatuses([])
    setRoles([])
    setConfirms([])
    setResults([])
    setLinks([])
    setAnswer('')
    setError(null)
    setLoading(true)

    const onEvent = (event: AgentEvent) => {
      switch (event.type) {
        case 'status':
          setStatuses((p) => [...p, event.label])
          break
        case 'role':
          setRoles((p) => [...p, { role: event.role, text: event.text }])
          break
        case 'confirm':
          setConfirms((p) => [...p, event.confirm])
          break
        case 'links':
          setLinks(event.links)
          break
        case 'answer':
          setAnswer(event.text)
          break
        case 'error':
          setError(event.message)
          break
        case 'sources':
          break
      }
    }

    try {
      await askAgent(trimmed, onEvent, controller.signal)
    } catch {
      if (!controller.signal.aborted) setError('Something went wrong.')
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  async function confirm(c: AgentConfirm) {
    setConfirms((p) => p.filter((x) => x.token !== c.token))
    try {
      const result = await confirmAction(c.token)
      setResults((p) => [...p, result])
    } catch {
      setError('Could not confirm that action.')
    }
  }

  const lastStatus = statuses[statuses.length - 1]

  return (
    <div className="mx-auto w-full max-w-2xl rounded-xl border border-white/10 bg-[#0e1015]">
      <form
        onSubmit={(e) => {
          e.preventDefault()
          void run(question)
        }}
        className="flex items-center gap-2.5 border-b border-white/10 px-4"
      >
        {loading ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-cyan-400" />
        ) : (
          <Sparkles className="h-4 w-4 shrink-0 text-cyan-400" />
        )}
        <input
          type="text"
          value={question}
          onChange={(e) => setQuestion(e.target.value)}
          placeholder="Ask your analyst — e.g. best pick tonight, sized for my bankroll"
          className="min-w-0 flex-1 bg-transparent py-3.5 text-sm text-zinc-100 placeholder:text-zinc-600 outline-none"
        />
      </form>

      <div className="max-h-[64vh] overflow-y-auto">
        {loading && lastStatus && (
          <div className="flex items-center gap-2 px-4 py-3 text-sm text-zinc-400">
            <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-400" />
            {lastStatus}
          </div>
        )}

        {/* bull / skeptic / judge debate turns */}
        {roles.map((turn, i) => {
          const meta = ROLE_META[turn.role] ?? {
            label: turn.role,
            icon: Sparkles,
            cls: 'text-zinc-300 border-white/10',
          }
          const Icon = meta.icon
          return (
            <div key={i} className={cn('mx-4 my-2 rounded-lg border bg-white/[0.02] p-3', meta.cls)}>
              <p className="flex items-center gap-1.5 pb-1 text-[10px] uppercase tracking-[0.12em]">
                <Icon className="h-3 w-3" />
                {meta.label}
              </p>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-100">{turn.text}</p>
            </div>
          )
        })}

        {/* write proposals awaiting confirmation (human-in-the-loop) */}
        {confirms.map((c) => (
          <div
            key={c.token}
            className="mx-4 my-2 rounded-lg border border-cyan-400/30 bg-cyan-400/[0.04] p-3"
          >
            <p className="pb-2 text-sm text-zinc-100">{c.summary}</p>
            <button
              type="button"
              onClick={() => void confirm(c)}
              className="rounded-md bg-cyan-500/90 px-3 py-1.5 text-xs font-medium text-black transition-colors hover:bg-cyan-400"
            >
              Confirm
            </button>
          </div>
        ))}

        {results.map((r, i) => (
          <div key={i} className="mx-4 my-2 flex items-center gap-2 text-sm text-emerald-300">
            <Check className="h-4 w-4" />
            {r}
          </div>
        ))}

        {links.length > 0 && (
          <div className="border-t border-white/10 py-1.5">
            {links.map((link) => (
              <button
                key={link.href}
                type="button"
                onClick={() => router.push(link.href)}
                className="group flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-white/5"
              >
                <ArrowRight className="h-4 w-4 shrink-0 text-cyan-400/70" />
                <span className="flex-1 text-sm text-zinc-100">{link.label}</span>
                <span className="text-xs text-zinc-600 group-hover:text-zinc-400">{link.href}</span>
              </button>
            ))}
          </div>
        )}

        {answer && (
          <div className="border-t border-white/10 px-4 py-3.5">
            <p className="flex items-center gap-1.5 pb-1.5 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
              <Sparkles className="h-3 w-3 text-cyan-400" />
              Analyst
            </p>
            <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-100">{answer}</p>
          </div>
        )}

        {error && <div className="border-t border-white/10 px-4 py-3 text-sm text-red-300">{error}</div>}
      </div>

      {asked && (
        <div className="flex items-center gap-1.5 border-t border-white/10 px-4 py-2 text-[11px] text-zinc-600">
          <Check className="h-3 w-3 text-cyan-400/60" />
          Grounded in Diamond&apos;s live model data · writes require your confirmation · not betting advice
        </div>
      )}
    </div>
  )
}
