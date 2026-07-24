import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { createProject, processProject } from '../api'
import { FileDrop } from '../components/FileDrop'
import { ProgressBar } from '../components/ProgressBar'

export function UploadPage() {
  const navigate = useNavigate()
  const [file, setFile] = useState<File | null>(null)
  const [targetMinutes, setTargetMinutes] = useState('')
  const [focus, setFocus] = useState('')
  const [busy, setBusy] = useState(false)
  const [phase, setPhase] = useState<'idle' | 'upload' | 'process'>('idle')
  const [progress, setProgress] = useState(0)
  const [step, setStep] = useState('')
  const [message, setMessage] = useState('')
  const [error, setError] = useState<string | null>(null)

  const onProcess = async () => {
    if (!file || busy) return
    setBusy(true)
    setError(null)
    setProgress(0)
    setStep('upload')
    setMessage('Uploading video…')
    setPhase('upload')

    try {
      const { project_id } = await createProject(file)
      setPhase('process')
      setProgress(0.02)
      setMessage('Upload complete — starting pipeline…')

      const minutes = targetMinutes.trim()
        ? Number.parseFloat(targetMinutes)
        : null
      if (minutes !== null && (!Number.isFinite(minutes) || minutes <= 0)) {
        throw new Error('Target minutes must be a positive number')
      }

      await processProject(
        project_id,
        {
          focus: focus.trim() || null,
          target_minutes: minutes,
        },
        (evt) => {
          setProgress(evt.progress)
          setStep(evt.step)
          setMessage(evt.message ?? '')
        },
      )

      navigate(`/projects/${project_id}`)
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err))
      setBusy(false)
      setPhase('idle')
    }
  }

  return (
    <div className="relative min-h-screen overflow-hidden bg-panel text-ink">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top,_rgba(124,92,255,0.18)_0%,_transparent_55%),radial-gradient(ellipse_at_bottom_right,_rgba(62,207,142,0.08)_0%,_transparent_45%)]"
      />
      <div className="relative mx-auto flex min-h-screen max-w-2xl flex-col justify-center px-6 py-16">
        <header className="mb-10 space-y-3">
          <p className="font-display text-5xl font-extrabold tracking-tight text-ink sm:text-6xl">
            autocutter
          </p>
          <p className="max-w-md text-lg leading-relaxed text-slate">
            Drop long-form footage. Set a length and theme. Get a rough cut you can
            refine.
          </p>
        </header>

        <div className="space-y-6 rounded-2xl bg-panel-2 p-6 shadow-lg shadow-black/40 ring-1 ring-white/10 sm:p-8">
          <FileDrop file={file} disabled={busy} onFile={setFile} />

          <div className="grid gap-5 sm:grid-cols-2">
            <label className="block space-y-2">
              <span className="text-sm font-medium text-ink">Target length (minutes)</span>
              <input
                type="number"
                min={1}
                step="any"
                placeholder="e.g. 30"
                value={targetMinutes}
                disabled={busy}
                onChange={(e) => setTargetMinutes(e.target.value)}
                className="w-full rounded-xl bg-panel px-3.5 py-3 text-ink outline-none ring-1 ring-white/10 transition placeholder:text-slate/60 focus:ring-2 focus:ring-accent disabled:opacity-50"
              />
            </label>
            <label className="block space-y-2 sm:col-span-1">
              <span className="text-sm font-medium text-ink">Whisper model</span>
              <div className="rounded-xl bg-panel px-3.5 py-3 text-sm text-slate ring-1 ring-white/10">
                from env / medium
              </div>
            </label>
          </div>

          <label className="block space-y-2">
            <span className="text-sm font-medium text-ink">Focus / theme</span>
            <textarea
              rows={2}
              placeholder='e.g. "Life on Long Island as new grads who also hate it here"'
              value={focus}
              disabled={busy}
              onChange={(e) => setFocus(e.target.value)}
              className="w-full resize-none rounded-xl bg-panel px-3.5 py-3 text-ink outline-none ring-1 ring-white/10 transition placeholder:text-slate/60 focus:ring-2 focus:ring-accent disabled:opacity-50"
            />
          </label>

          {busy ? (
            <div className="rounded-xl bg-panel px-4 py-4 ring-1 ring-white/10">
              <ProgressBar
                progress={phase === 'upload' ? Math.max(progress, 0.05) : progress}
                step={step}
                message={message}
              />
            </div>
          ) : null}

          {error ? (
            <p className="rounded-xl bg-cut/10 px-3.5 py-3 text-sm text-cut ring-1 ring-cut/30">
              {error}
            </p>
          ) : null}

          <button
            type="button"
            disabled={!file || busy}
            onClick={() => void onProcess()}
            className="w-full rounded-xl bg-accent px-4 py-3.5 font-display text-lg font-bold text-white shadow-lg shadow-accent/25 transition hover:bg-accent-dim disabled:cursor-not-allowed disabled:opacity-40 disabled:shadow-none"
          >
            {busy ? (phase === 'upload' ? 'Uploading…' : 'Processing…') : 'Process'}
          </button>
        </div>
      </div>
    </div>
  )
}
