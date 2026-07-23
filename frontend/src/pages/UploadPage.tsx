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
    <div className="relative min-h-screen overflow-hidden">
      <div
        aria-hidden
        className="pointer-events-none absolute inset-0 bg-[radial-gradient(ellipse_at_top_left,_#ffe8d6_0%,_transparent_50%),radial-gradient(ellipse_at_bottom_right,_#d9ebe7_0%,_transparent_45%)]"
      />
      <div className="relative mx-auto flex min-h-screen max-w-2xl flex-col justify-center px-6 py-16">
        <header className="mb-10">
          <p className="font-display text-5xl font-extrabold tracking-tight text-ink sm:text-6xl">
            autocutter
          </p>
          <p className="mt-3 max-w-md text-lg text-slate">
            Drop long-form footage. Set a length and theme. Get a rough cut you can
            refine.
          </p>
        </header>

        <div className="space-y-6 rounded-3xl bg-white/70 p-6 shadow-sm ring-1 ring-ink/5 backdrop-blur sm:p-8">
          <FileDrop file={file} disabled={busy} onFile={setFile} />

          <div className="grid gap-4 sm:grid-cols-2">
            <label className="block space-y-1.5">
              <span className="text-sm font-medium text-ink">Target length (minutes)</span>
              <input
                type="number"
                min={1}
                step="any"
                placeholder="e.g. 30"
                value={targetMinutes}
                disabled={busy}
                onChange={(e) => setTargetMinutes(e.target.value)}
                className="w-full rounded-xl border border-ink/15 bg-paper px-3 py-2.5 outline-none ring-accent focus:ring-2 disabled:opacity-60"
              />
            </label>
            <label className="block space-y-1.5 sm:col-span-1">
              <span className="text-sm font-medium text-ink">Whisper model</span>
              <div className="rounded-xl border border-ink/10 bg-mist/50 px-3 py-2.5 text-sm text-slate">
                from env / medium
              </div>
            </label>
          </div>

          <label className="block space-y-1.5">
            <span className="text-sm font-medium text-ink">Focus / theme</span>
            <textarea
              rows={2}
              placeholder='e.g. "Life on Long Island as new grads who also hate it here"'
              value={focus}
              disabled={busy}
              onChange={(e) => setFocus(e.target.value)}
              className="w-full resize-none rounded-xl border border-ink/15 bg-paper px-3 py-2.5 outline-none ring-accent focus:ring-2 disabled:opacity-60"
            />
          </label>

          {busy ? (
            <ProgressBar
              progress={phase === 'upload' ? Math.max(progress, 0.05) : progress}
              step={step}
              message={message}
            />
          ) : null}

          {error ? (
            <p className="rounded-xl bg-red-50 px-3 py-2 text-sm text-red-700 ring-1 ring-red-200">
              {error}
            </p>
          ) : null}

          <button
            type="button"
            disabled={!file || busy}
            onClick={() => void onProcess()}
            className="w-full rounded-xl bg-ink px-4 py-3.5 font-display text-lg font-bold text-paper transition hover:bg-ink/90 disabled:cursor-not-allowed disabled:opacity-40"
          >
            {busy ? (phase === 'upload' ? 'Uploading…' : 'Processing…') : 'Process'}
          </button>
        </div>
      </div>
    </div>
  )
}
