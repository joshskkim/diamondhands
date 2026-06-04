import type { ReactNode } from 'react'
import { cn } from '@/lib/utils'

type ComingSoonProps = {
  title: string
  description: string
  icon?: ReactNode
}

export function ComingSoon({ title, description, icon }: ComingSoonProps) {
  return (
    <main className="max-w-3xl mx-auto w-full px-4 py-16">
      <div className="bg-[#0e1015] border border-white/10 rounded-xl px-6 py-12 flex flex-col items-center text-center">
        {icon ? (
          <div
            className={cn(
              'flex h-14 w-14 items-center justify-center rounded-full',
              'bg-cyan-500/10 text-cyan-400',
            )}
          >
            {icon}
          </div>
        ) : null}
        <h1 className="mt-6 text-2xl font-semibold tracking-tight text-zinc-100">
          {title}
        </h1>
        <p className="mt-2 max-w-md text-sm text-zinc-400">{description}</p>
        <span className="mt-6 text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium">
          Coming soon
        </span>
      </div>
    </main>
  )
}
