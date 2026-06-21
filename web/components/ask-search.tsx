'use client'

import { useEffect, useRef, useState } from 'react'
import { useRouter } from 'next/navigation'
import { Search, Sparkles, ArrowRight, Loader2, Check } from 'lucide-react'
import { askDiamond, type AskEvent, type AskLink } from '@/lib/api'
import { cn } from '@/lib/utils'

const EXAMPLES = [
  'Aaron Judge',
  'Best EV bet today?',
  "Model's top hit pick tonight",
]

/**
 * Global "Ask Diamond" command palette. A search box that streams a grounded answer plus
 * navigable result rows (deep links to the relevant pages). Rendered only while open, so each
 * invocation starts fresh. Esc / backdrop closes; clicking a result navigates and closes.
 */
export function AskSearch({ onClose }: { onClose: () => void }) {
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement>(null)
  const abortRef = useRef<AbortController | null>(null)

  const [question, setQuestion] = useState('')
  const [statuses, setStatuses] = useState<string[]>([])
  const [links, setLinks] = useState<AskLink[]>([])
  const [answer, setAnswer] = useState('')
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(false)
  const [asked, setAsked] = useState(false)

  // Focus the input on open; close on Esc; abort any in-flight stream on unmount.
  useEffect(() => {
    inputRef.current?.focus()
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    window.addEventListener('keydown', onKey)
    return () => {
      window.removeEventListener('keydown', onKey)
      abortRef.current?.abort()
    }
  }, [onClose])

  async function run(q: string) {
    const trimmed = q.trim()
    if (!trimmed || loading) return
    abortRef.current?.abort()
    const controller = new AbortController()
    abortRef.current = controller

    setQuestion(trimmed)
    setAsked(true)
    setStatuses([])
    setLinks([])
    setAnswer('')
    setError(null)
    setLoading(true)

    const onEvent = (event: AskEvent) => {
      switch (event.type) {
        case 'status':
          setStatuses((prev) => [...prev, event.label])
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
      await askDiamond(trimmed, onEvent, controller.signal)
    } catch {
      if (!controller.signal.aborted) setError('Something went wrong.')
    } finally {
      if (!controller.signal.aborted) setLoading(false)
    }
  }

  function go(href: string) {
    router.push(href)
    onClose()
  }

  const lastStatus = statuses[statuses.length - 1]

  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center px-4 pt-[12vh]">
      <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={onClose} aria-hidden />

      <div className="relative w-full max-w-xl overflow-hidden rounded-xl border border-white/10 bg-[#0e1015] shadow-2xl">
        {/* search input */}
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
            <Search className="h-4 w-4 shrink-0 text-zinc-500" />
          )}
          <input
            ref={inputRef}
            type="text"
            value={question}
            onChange={(e) => setQuestion(e.target.value)}
            placeholder="Ask Diamond — a player, a bet, today's slate…"
            className="min-w-0 flex-1 bg-transparent py-3.5 text-sm text-zinc-100 placeholder:text-zinc-600 outline-none"
          />
          <kbd className="hidden rounded border border-white/10 px-1.5 py-0.5 text-[10px] text-zinc-500 sm:inline">
            esc
          </kbd>
        </form>

        <div className="max-h-[60vh] overflow-y-auto">
          {/* before first ask: example chips */}
          {!asked && (
            <div className="p-3">
              <p className="px-1 pb-2 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
                Try
              </p>
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

          {/* live status while the agent works */}
          {loading && lastStatus && (
            <div className="flex items-center gap-2 px-4 py-3 text-sm text-zinc-400">
              <Loader2 className="h-3.5 w-3.5 animate-spin text-cyan-400" />
              {lastStatus}
            </div>
          )}

          {/* navigable result rows */}
          {links.length > 0 && (
            <div className="border-t border-white/10 py-1.5 first:border-t-0">
              {links.map((link) => (
                <button
                  key={link.href}
                  type="button"
                  onClick={() => go(link.href)}
                  className="group flex w-full items-center gap-3 px-4 py-2.5 text-left transition-colors hover:bg-white/5"
                >
                  <ArrowRight className="h-4 w-4 shrink-0 text-cyan-400/70" />
                  <span className="flex-1 text-sm text-zinc-100">{link.label}</span>
                  <span className="text-xs text-zinc-600 group-hover:text-zinc-400">{link.href}</span>
                </button>
              ))}
            </div>
          )}

          {/* the answer */}
          {answer && (
            <div className="border-t border-white/10 px-4 py-3.5">
              <p className="flex items-center gap-1.5 pb-1.5 text-[10px] uppercase tracking-[0.12em] text-zinc-500">
                <Sparkles className="h-3 w-3 text-cyan-400" />
                Answer
              </p>
              <p className="whitespace-pre-wrap text-sm leading-relaxed text-zinc-100">{answer}</p>
            </div>
          )}

          {error && (
            <div className="border-t border-white/10 px-4 py-3 text-sm text-red-300">{error}</div>
          )}

          {/* completed-but-no-output edge */}
          {asked && !loading && !answer && !error && links.length === 0 && (
            <div className="px-4 py-3 text-sm text-zinc-500">No results.</div>
          )}
        </div>

        {asked && (
          <div className="flex items-center gap-1.5 border-t border-white/10 px-4 py-2 text-[11px] text-zinc-600">
            <Check className="h-3 w-3 text-cyan-400/60" />
            Grounded in Diamond&apos;s live model data · not betting advice
          </div>
        )}
      </div>
    </div>
  )
}
