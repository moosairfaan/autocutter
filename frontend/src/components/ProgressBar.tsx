type Props = {
  progress: number
  message?: string
  step?: string
}

export function ProgressBar({ progress, message, step }: Props) {
  const pct = Math.round(Math.max(0, Math.min(1, progress)) * 100)
  return (
    <div className="w-full space-y-2">
      <div className="flex items-baseline justify-between gap-3 text-sm">
        <span className="font-medium text-ink">
          {step ? <span className="capitalize">{step}</span> : 'Working'}
          {message ? <span className="text-slate"> — {message}</span> : null}
        </span>
        <span className="font-mono text-slate">{pct}%</span>
      </div>
      <div className="h-2.5 overflow-hidden rounded-full bg-mist">
        <div
          className="h-full rounded-full bg-accent transition-[width] duration-300 ease-out"
          style={{ width: `${pct}%` }}
        />
      </div>
    </div>
  )
}
