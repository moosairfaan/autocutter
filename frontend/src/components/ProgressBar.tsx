type Props = {
  progress: number
  message?: string
  step?: string
}

export function ProgressBar({ progress, message, step }: Props) {
  const pct = Math.round(Math.max(0, Math.min(1, progress)) * 100)
  return (
    <div className="w-full space-y-3">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium text-ink">
          {step ? <span className="capitalize text-accent">{step}</span> : 'Working'}
          {message ? <span className="text-slate"> — {message}</span> : null}
        </span>
        <span className="font-mono text-xs tabular-nums text-slate">{pct}%</span>
      </div>
      <div className="h-2 overflow-hidden rounded-full bg-mist">
        <div
          className="h-full rounded-full bg-gradient-to-r from-accent-dim to-accent shadow-[0_0_12px_rgba(124,92,255,0.45)] transition-[width] duration-500 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
