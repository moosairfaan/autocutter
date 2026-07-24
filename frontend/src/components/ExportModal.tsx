import { ProgressBar } from './ProgressBar'

type Phase = 'options' | 'running' | 'done' | 'error'

export type ExportResolution = 'original' | '1080p' | '720p'

type Props = {
  open: boolean
  phase: Phase
  cleanAudio: boolean
  onCleanAudioChange: (value: boolean) => void
  resolution: ExportResolution
  onResolutionChange: (value: ExportResolution) => void
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
  resolution,
  onResolutionChange,
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
      className="fixed inset-0 z-50 flex items-center justify-center bg-panel/80 p-4 backdrop-blur-sm"
      role="dialog"
      aria-modal="true"
      aria-labelledby="export-modal-title"
    >
      <div className="w-full max-w-md rounded-2xl bg-panel-2 p-6 shadow-2xl shadow-black/50 ring-1 ring-white/10 sm:p-7">
        <h2
          id="export-modal-title"
          className="font-display text-xl font-bold tracking-tight text-ink"
        >
          {title}
        </h2>

        <div className="mt-6 space-y-5">
          {phase === 'options' ? (
            <>
              <p className="text-sm leading-relaxed text-slate">
                Renders your kept clips (with trims and order) into a single MP4.
              </p>
              <label className="block space-y-2">
                <span className="text-sm font-medium text-ink">Resolution</span>
                <select
                  value={resolution}
                  onChange={(e) =>
                    onResolutionChange(e.target.value as ExportResolution)
                  }
                  className="w-full rounded-xl bg-panel px-3.5 py-3 text-sm text-ink outline-none ring-1 ring-white/10 transition focus:ring-2 focus:ring-accent"
                >
                  <option value="original">Original (source size)</option>
                  <option value="1080p">1080p (keep aspect ratio)</option>
                  <option value="720p">720p (keep aspect ratio)</option>
                </select>
                <span className="block text-xs leading-relaxed text-slate">
                  Lower resolutions encode much faster on 4K clips. Default is
                  Original.
                </span>
              </label>
              <label className="flex cursor-pointer items-start gap-3 rounded-xl bg-panel px-4 py-3.5 ring-1 ring-white/10 transition hover:ring-accent/40">
                <input
                  type="checkbox"
                  checked={cleanAudio}
                  onChange={(e) => onCleanAudioChange(e.target.checked)}
                  className="mt-1 h-4 w-4 accent-accent"
                />
                <span>
                  <span className="block text-sm font-medium text-ink">
                    Audio cleanup
                  </span>
                  <span className="mt-1 block text-xs leading-relaxed text-slate">
                    Light denoise, level matching across splices, and strip only extreme
                    dead air (&gt;2s). Off by default.
                  </span>
                </span>
              </label>
            </>
          ) : null}

          {phase === 'error' ? (
            <p className="rounded-xl bg-cut/10 px-4 py-3 text-sm text-cut ring-1 ring-cut/30">
              {error}
            </p>
          ) : null}

          {phase === 'done' ? (
            <div className="space-y-3 rounded-xl bg-ok/10 px-4 py-4 ring-1 ring-ok/30">
              <p className="text-sm font-medium text-ok">Export complete</p>
              <p className="text-sm leading-relaxed text-slate">
                Your rough cut is rendered. Download the MP4 to keep editing elsewhere.
              </p>
            </div>
          ) : null}

          {phase === 'running' ? (
            <div className="rounded-xl bg-panel px-4 py-4 ring-1 ring-white/10">
              <ProgressBar progress={progress} step={step} message={message} />
            </div>
          ) : null}
        </div>

        <div className="mt-7 flex flex-wrap items-center justify-end gap-3">
          {phase === 'options' ? (
            <>
              <button
                type="button"
                onClick={onClose}
                className="rounded-xl bg-white/5 px-4 py-2.5 text-sm font-medium text-ink ring-1 ring-white/10 transition hover:bg-white/10"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={onStart}
                className="rounded-xl bg-accent px-5 py-2.5 font-display text-sm font-bold text-white shadow-md shadow-accent/25 transition hover:bg-accent-dim"
              >
                Start export
              </button>
            </>
          ) : null}

          {phase === 'done' ? (
            <a
              href={downloadUrl}
              download
              className="rounded-xl bg-ok px-5 py-2.5 font-display text-sm font-bold text-panel shadow-md shadow-ok/20 transition hover:brightness-110"
            >
              Download
            </a>
          ) : null}

          {phase === 'done' || phase === 'error' ? (
            <button
              type="button"
              onClick={onClose}
              className="rounded-xl bg-white/5 px-4 py-2.5 text-sm font-medium text-ink ring-1 ring-white/10 transition hover:bg-white/10"
            >
              Close
            </button>
          ) : null}

          {phase === 'running' ? (
            <button
              type="button"
              disabled
              className="rounded-xl bg-white/5 px-4 py-2.5 text-sm font-medium text-slate opacity-50 ring-1 ring-white/10"
            >
              Working…
            </button>
          ) : null}
        </div>
      </div>
    </div>
  )
}
