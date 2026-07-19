import { ProgressBar } from './ProgressBar'

type Phase = 'options' | 'running' | 'done' | 'error'

type Props = {
  open: boolean
  phase: Phase
  cleanAudio: boolean
  onCleanAudioChange: (value: boolean) => void
  progress: number
  step: string
  message: string
  error: string | null
  downloadUrl: string
  onStart: () => void
  onClose: () => void
}

export function ExportModal({
  open,
  phase,
  cleanAudio,
  onCleanAudioChange,
  progress,
  step,
  message,
  error,
  downloadUrl,
  onStart,
  onClose,
}: Props) {
  if (!open) return null

  const title =
    phase === 'done'
      ? 'Export ready'
      : phase === 'error'
        ? 'Export failed'
        : phase === 'running'
          ? 'Exporting…'
          : 'Export options'

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/70 p-4"
      role="dialog"
      aria-modal="true"
      aria-labelledby="export-modal-title"
    >
      <div className="w-full max-w-md rounded-2xl bg-panel-2 p-6 shadow-xl ring-1 ring-white/15">
        <h2
          id="export-modal-title"
          className="font-display text-xl font-bold text-white"
        >
          {title}
        </h2>

        <div className="mt-5 space-y-4">
          {phase === 'options' ? (
            <>
              <p className="text-sm text-mist">
                Renders your kept clips (with trims and order) into a single MP4.
              </p>
              <label className="flex cursor-pointer items-start gap-3 rounded-xl bg-panel px-3 py-3 ring-1 ring-white/10">
                <input
                  type="checkbox"
                  checked={cleanAudio}
                  onChange={(e) => onCleanAudioChange(e.target.checked)}
                  className="mt-1 h-4 w-4 accent-accent"
                />
                <span>
                  <span className="block text-sm font-medium text-white">
                    Audio cleanup
                  </span>
                  <span className="mt-0.5 block text-xs leading-relaxed text-slate">
                    Light denoise, level matching across splices, and strip only extreme
                    dead air (&gt;2s). Off by default.
                  </span>
                </span>
              </label>
            </>
          ) : null}

          {phase === 'error' ? (
            <p className="rounded-xl bg-red-950/60 px-3 py-2 text-sm text-red-200 ring-1 ring-red-500/40">
              {error}
            </p>
          ) : null}

          {phase === 'done' ? (
            <p className="text-sm text-mist">
              Your rough cut is rendered. Download the MP4 to keep editing elsewhere.
            </p>
          ) : null}

          {phase === 'running' ? (
            <ProgressBar progress={progress} step={step} message={message} />
          ) : null}
        </div>

        <div className="mt-6 flex flex-wrap items-center justify-end gap-3">
          {phase === 'options' ? (
            <>
              <button
                type="button"
                onClick={onClose}
                className="rounded-lg bg-white/10 px-4 py-2 text-sm font-medium text-paper transition hover:bg-white/15"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={onStart}
                className="rounded-lg bg-accent px-4 py-2 font-display text-sm font-bold text-white transition hover:bg-accent-dim"
              >
                Start export
              </button>
            </>
          ) : null}

          {phase === 'done' ? (
            <a
              href={downloadUrl}
              download
              className="rounded-lg bg-ok px-4 py-2 font-display text-sm font-bold text-white transition hover:brightness-110"
            >
              Download
            </a>
          ) : null}

          {phase === 'done' || phase === 'error' ? (
            <button
              type="button"
              onClick={onClose}
              className="rounded-lg bg-white/10 px-4 py-2 text-sm font-medium text-paper transition hover:bg-white/15"
            >
              Close
            </button>
          ) : null}

          {phase === 'running' ? (
            <button
              type="button"
              disabled
              className="rounded-lg bg-white/10 px-4 py-2 text-sm font-medium text-paper opacity-40"
            >
              Working…
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
