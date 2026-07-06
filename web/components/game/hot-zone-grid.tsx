import { microLabel } from '@/components/ui/primitives'

/**
 * Strike-zone hot-zone placeholder. A clean 3×3 grid inside a chase border,
 * rendered ghosted with a "coming soon" label until real per-zone xwOBA
 * (plate_x/plate_z) data is wired up. Kept compact so it never crowds the view.
 */
export function HotZoneGrid({ label = 'Hitting hot zones' }: { label?: string }) {
  const cells = Array.from({ length: 9 })
  return (
    <div>
      <div className={microLabel}>{label}</div>
      <div className="mt-2 flex items-center gap-4">
        <div className="relative">
          {/* chase border */}
          <div className="rounded-md border border-dashed border-white/15 p-1.5">
            {/* 3×3 strike zone */}
            <div className="grid grid-cols-3 grid-rows-3 gap-0.5">
              {cells.map((_, i) => (
                <div
                  key={i}
                  className="h-7 w-7 rounded-sm bg-white/[0.04] ring-1 ring-inset ring-white/5"
                />
              ))}
            </div>
          </div>
          {/* catcher's-eye home plate notch */}
          <div className="mx-auto mt-1 h-1.5 w-6 [clip-path:polygon(0_0,100%_0,50%_100%)] bg-white/10" />
        </div>
        <p className="text-[11px] text-zinc-500 leading-relaxed max-w-[12rem]">
          Per-zone xwOBA heatmap — <span className="text-cyan-300">coming soon</span> with the
          batted-ball data pipeline.
        </p>
      </div>
    </div>
  )
}
