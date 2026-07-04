'use client'

import { useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Sparkles, ArrowRight, Loader2, Check, ShieldQuestion, Swords, Gavel, Plus } from 'lucide-react'
import {
  askAgent,
  confirmAction,
  type AgentEvent,
  type AgentConfirm,
  type AskLink,
} from '@/lib/api'
import { cn } from '@/lib/utils'

type RoleTurn = { role: string; text: string }

type Turn = {
  question: string
  statuses: string[]
  roles: RoleTurn[]
  confirms: AgentConfirm[]
  results: string[]
  links: AskLink[]
  answer: string
  error: string | null
  loading: boolean
}

const ROLE_META: Record<string, { label: string; icon: typeof Swords; cls: string }> = {
  bull: { label: 'Bull', icon: Swords, cls: 'text-emerald-300 border-emerald-400/30' },
  skeptic: { label: 'Skeptic', icon: ShieldQuestion, cls: 'text-amber-300 border-amber-400/30' },
  judge: { label: 'Judge', icon: Gavel, cls: 'text-cyan-300 border-cyan-400/30' },
}

const EXAMPLES = ['Best EV pick tonight?', "Model's top hit pick", 'Set my bankroll to 100 units']

/**
 * The Diamond Analyst panel: a multi-turn conversation. The thread id (returned on the first turn)
 * is sent back with each follow-up so "size that one" resolves in context; "New chat" starts fresh.
 * Streams the live tool feed, the bull/skeptic/judge debate, and write proposals (which the user
 * must confirm — the model never executes a write itself).
 */
export function AgentPanel() {
  const router = useRouter()
  const abortRef = useRef<AbortController | null>(null)
  const [input, setInput] = useState('')
  const [threadId, setThreadId] = useState<number | null>(null)
  const [turns, setTurns] = useState<Turn[]>([])

  const loading = turns.length > 0 && turns[turns.length - 1].loading

  function updateLast(fn: (t: Turn) => Turn) {
    setTurns((prev) => prev.map((t, i) => (i === prev.length - 1 ? fn(t) : t)))
  }

  async function run(q: string) {
    const trimmed = q.trim()
    if (!trimmed || loading) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller
    setInput('')
    setTurns((prev) => [
      ...prev,
      { question: trimmed, statuses: [], roles: [], confirms: [], results: [], links: [], answer: '', error: null, loading: true },
    ])

    const onEvent = (event: AgentEvent) => {
      switch (event.type) {
        case 'thread':
          setThreadId(event.threadId)
          break
        case 'status':
          updateLast((t) => ({ ...t, statuses: [...t.statuses, event.label] }))
          break
        case 'role':
          updateLast((t) => ({ ...t, roles: [...t.roles, { role: event.role, text: event.text }] }))
          break
        case 'confirm':
          updateLast((t) => ({ ...t, confirms: [...t.confirms, event.confirm] }))
          break
        case 'links':
          updateLast((t) => ({ ...t, links: event.links }))
          break
        case 'answer':
          updateLast((t) => ({ ...t, answer: event.text }))
          break
        case 'error':
          updateLast((t) => ({ ...t, error: event.message }))
          break
        case 'sources':
          break
      }
    }

    try {
      await askAgent(trimmed, onEvent, controller.signal, threadId)
    } catch {
      if (!controller.signal.aborted) updateLast((t) => ({ ...t, error: 'Something went wrong.' }))
    } finally {
      if (!controller.signal.aborted) updateLast((t) => ({ ...t, loading: false }))
    }
  }

  async function confirm(turnIdx: number, c: AgentConfirm) {
    setTurns((prev) =>
      prev.map((t, i) => (i === turnIdx ? { ...t, confirms: t.confirms.filter((x) => x.token !== c.token) } : t)),
    )
    try {
      const result = await confirmAction(c.token)
      setTurns((prev) => prev.map((t, i) => (i === turnIdx ? { ...t, results: [...t.results, result] } : t)))
    } catch {
      setTurns((prev) => prev.map((t, i) => (i === turnIdx ? { ...t, error: 'Could not confirm that action.' } : t)))
    }
  }

  function newChat() {
    abortRef.current?.abort()
    setTurns([])
    setThreadId(null)
    setInput('')
  }

  return (
    <div className="mx-auto flex w-full max-w-2xl flex-col rounded-xl border border-white/10 bg-[#0e1015]">
      {turns.length > 0 && (
        <div className="flex items-center justify-between border-b border-white/10 px-4 py-2">
          <span className="text-[11px] text-zinc-500">{loading ? 'Thinking…' : 'Conversation'}</span>
          <button
            type="button"
            onClick={newChat}
            className="inline-flex items-center gap-1 rounded-md border border-white/10 px-2 py-1 text-[11px] text-zinc-400 transition-colors hover:bg-white/5 hover:text-zinc-100"
          >
            <Plus className="h-3 w-3" /> New chat
          </button>
        </div>
      )}

      <div className="max-h-[64vh] overflow-y-auto">
        {turns.length === 0 && (
          <div className="p-3">
            <p className="px-1 pb-2 text-[10px] uppercase tracking-[0.12em] text-zinc-500">Try</p>
            <div className="flex flex-wrap gap-1.5">
              {EXAMPLES.map((ex) => (
                <button
                  key={ex}
                  type="button"
                  onClick={() => void run(ex)}
                  className="rounded-full border border-white/10 px-3 py-1.5 text-xs text-zinc-400 transition-colors hover:border-cyan-400/30 hover:text-zinc-100"
                >
                  {ex}
                </button>
              ))}
            </div>
          </div>
        )}

        {turns.map((turn, idx) => {
          const isLast = idx === turns.length - 1
          const lastStatus = turn.statuses[turn.statuses.length - 1]
          return (
            <div key={idx} className="border-t border-white/5 first:border-t-0">
              {/* the user's message */}
              <div className="flex justify-end px-4 pt-3">
                <span className="max-w-[85%] rounded-2xl rounded-br-sm bg-cyan-500/15 px-3 py-1.5 text-sm text-zinc-100">
                  {turn.question}
                </span>
              </div>

              {isLast && turn.loading && lastStatus && (
                <div className="flex items-center gap-2 px-4 py-2 text-sm text-zinc-400">
                  <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-400" />
                  {lastStatus}
                </div>
              )}

              {turn.roles.map((r, i) => {
                const meta = ROLE_META[r.role] ?? { label: r.role, icon: Sparkles, cls: 'text-zinc-300 border-white/10' }
                const Icon = meta.icon
                return (
                  <div key={i} className={cn('mx-4 my-2 rounded-lg border bg-white/[0.02] p-3', meta.cls)}>
                    <p className="flex items-center gap-1.5 pb-1 text-[10px] uppercase tracking-[0.12em]">
                      <Icon className="h-3 w-3" />
                      {meta.label}
                    </p>
                    <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-100">{r.text}</p>
                  </div>
                )
              })}

              {turn.confirms.map((c) => (
                <div key={c.token} className="mx-4 my-2 rounded-lg border border-cyan-400/30 bg-cyan-400/[0.04] p-3">
                  <p className="pb-2 text-sm text-zinc-100">{c.summary}</p>
                  <button
                    type="button"
                    onClick={() => void confirm(idx, c)}
                    className="rounded-md bg-cyan-500/90 px-3 py-1.5 text-xs font-medium text-black transition-colors hover:bg-cyan-400"
                  >
                    Confirm
                  </button>
                </div>
              ))}

              {turn.results.map((r, i) => (
                <div key={i} className="mx-4 my-2 flex items-center gap-2 text-sm text-emerald-300">
                  <Check className="h-4 w-4" />
                  {r}
                </div>
              ))}

              {turn.links.length > 0 && (
                <div className="py-1">
                  {turn.links.map((link) => (
                    <button
                      key={link.href}
                      type="button"
                      onClick={() => router.push(link.href)}
                      className="group flex w-full items-center gap-3 px-4 py-2 text-left transition-colors hover:bg-white/5"
                    >
                      <ArrowRight className="h-4 w-4 shrink-0 text-cyan-400/70" />
                      <span className="flex-1 text-sm text-zinc-100">{link.label}</span>
                      <span className="text-xs text-zinc-600 group-hover:text-zinc-400">{link.href}</span>
                    </button>
                  ))}
                </div>
              )}

              {turn.answer && (
                <div className="px-4 py-3">
                  <p className="flex items-center gap-1.5 pb-1.5 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
                    <Sparkles className="h-3 w-3 text-cyan-400" />
                    Analyst
                  </p>
                  <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-100">{turn.answer}</p>
                </div>
              )}

              {turn.error && <div className="px-4 py-2 text-sm text-red-300">{turn.error}</div>}
            </div>
          )
        })}
      </div>

      <form
        onSubmit={(e) => {
          e.preventDefault()
          void run(input)
        }}
        className="flex items-center gap-2.5 border-t border-white/10 px-4"
      >
        {loading ? (
          <Loader2 className="h-4 w-4 shrink-0 animate-spin text-cyan-400" />
        ) : (
          <Sparkles className="h-4 w-4 shrink-0 text-cyan-400" />
        )}
        <input
          type="text"
          value={input}
          onChange={(e) => setInput(e.target.value)}
          placeholder={turns.length ? 'Ask a follow-up…' : 'Ask your analyst — e.g. best pick tonight, sized for my bankroll'}
          className="min-w-0 flex-1 bg-transparent py-3.5 text-sm text-zinc-100 placeholder:text-zinc-600 outline-none"
        />
      </form>

      {turns.length > 0 && (
        <div className="flex items-center gap-1.5 border-t border-white/10 px-4 py-2 text-[11px] text-zinc-600">
          <Check className="h-3 w-3 text-cyan-400/60" />
          Grounded in Diamond&apos;s live data · writes require your confirmation · not betting advice
        </div>
      )}
    </div>
  )
}
