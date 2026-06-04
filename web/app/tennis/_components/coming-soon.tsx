import type { LucideIcon } from "lucide-react";
import { Circle } from "lucide-react";
import { cn } from "@/lib/utils";

export function ComingSoon({
  label = "Tennis",
  title,
  description,
  icon: Icon = Circle,
  className,
}: {
  label?: string;
  title: string;
  description: string;
  icon?: LucideIcon;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "bg-[#0e1015] border border-white/10 rounded-xl px-6 py-12 text-center flex flex-col items-center gap-3",
        className,
      )}
    >
      <span className="flex h-12 w-12 items-center justify-center rounded-full border border-white/10 bg-white/5 text-cyan-400">
        <Icon className="h-6 w-6" aria-hidden />
      </span>
      <p className="text-[10px] uppercase tracking-[0.12em] text-zinc-500 font-medium">
        {label}
      </p>
      <h2 className="text-xl text-zinc-100">{title}</h2>
      <p className="text-sm text-zinc-400 max-w-md">{description}</p>
    </div>
  );
}
