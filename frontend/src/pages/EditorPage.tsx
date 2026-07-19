import { useEffect, useRef, useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  exportDownloadUrl,
  exportProject,
  fetchSegments,
  normalizeScoredSegments,
  patchSegments,
  videoUrl,
} from '../api'
import { ExportModal } from '../components/ExportModal'
import { Timeline } from '../components/Timeline'
import { VideoPlayer, type VideoPlayerHandle } from '../components/VideoPlayer'
import { mergeEditWithScored } from '../lib/segments'
import type { EditSegment, ScoredSegment } from '../types'

export function EditorPage() {
  const { projectId = '' } = useParams()
  const playerRef = useRef<VideoPlayerHandle>(null)

  const [scoredSegments, setScoredSegments] = useState<ScoredSegment[]>([])
  const [segments, setSegments] = useState<EditSegment[]>([])
  const [targetMinutes, setTargetMinutes] = useState<number | null>(null)
  const [focus, setFocus] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [saving, setSaving] = useState(false)
  const [saveMessage, setSaveMessage] = useState<string | null>(null)

  const [exportOpen, setExportOpen] = useState(false)
  const [exportPhase, setExportPhase] = useState<
    'options' | 'running' | 'done' | 'error'
  >('options')
  const [cleanAudio, setCleanAudio] = useState(false)
  const [exporting, setExporting] = useState(false)
  const [exportProgress, setExportProgress] = useState(0)
  const [exportStep, setExportStep] = useState('')
  const [exportMessage, setExportMessage] = useState('')
  const [exportError, setExportError] = useState<string | null>(null)

  useEffect(() => {
    if (!projectId) return
    let cancelled = false
    setLoading(true)
    setError(null)
    setSaveMessage(null)

    void fetchSegments(projectId)
      .then((data) => {
        if (cancelled) return
        const scored = normalizeScoredSegments(data.scored)
        setScoredSegments(scored)
        setSegments(mergeEditWithScored(data.edit_decision?.segments ?? null, scored))

        const tm = data.meta?.target_minutes
        setTargetMinutes(typeof tm === 'number' ? tm : null)

        if (!Array.isArray(data.scored) && data.scored.focus) {
          setFocus(data.scored.focus)
        } else if (typeof data.meta?.focus === 'string') {
          setFocus(data.meta.focus)
        } else {
          setFocus(null)
        }
      })
      .catch((err: unknown) => {
        if (!cancelled) {
          setError(err instanceof Error ? err.message : String(err))
        }
      })
      .finally(() => {
        if (!cancelled) setLoading(false)
      })

    return () => {
      cancelled = true
    }
  }, [projectId])

  const onSave = async () => {
    if (!projectId || saving) return
    setSaving(true)
    setSaveMessage(null)
    try {
      await patchSegments(projectId, segments)
      setSaveMessage('Saved')
      window.setTimeout(() => setSaveMessage(null), 2500)
    } catch (err) {
      setSaveMessage(err instanceof Error ? err.message : String(err))
    } finally {
      setSaving(false)
    }
  }

  const openExportModal = () => {
    if (exporting) return
    setExportOpen(true)
    setExportPhase('options')
    setCleanAudio(false)
    setExportError(null)
    setExportProgress(0)
    setExportStep('')
    setExportMessage('')
  }

  const startExport = async () => {
    if (!projectId || exporting) return
    setExportPhase('running')
    setExporting(true)
    setExportError(null)
    setExportProgress(0)
    setExportStep('save')
    setExportMessage('Saving edit decision…')

    try {
      await patchSegments(projectId, segments)
      setExportStep('export')
      setExportMessage('Starting export…')
      await exportProject(
        projectId,
        (evt) => {
          setExportProgress(evt.progress)
          setExportStep(evt.step)
          setExportMessage(evt.message ?? '')
        },
        { clean_audio: cleanAudio },
      )
      setExportPhase('done')
      setExportProgress(1)
      setExportMessage('Export complete')
    } catch (err) {
      setExportError(err instanceof Error ? err.message : String(err))
      setExportPhase('error')
    } finally {
      setExporting(false)
    }
  }

  return (
    <div className="min-h-screen bg-panel text-paper">
      <header className="flex items-center justify-between gap-4 border-b border-white/10 px-6 py-4">
        <div className="flex items-center gap-4">
          <Link
            to="/"
            className="font-display text-lg font-bold tracking-tight text-accent hover:text-white"
          >
            autocutter
          </Link>
          <span className="font-mono text-xs text-slate">{projectId}</span>
        </div>
        <div className="text-sm text-mist">
          {loading
            ? 'Loading segments…'
            : `${scoredSegments.length} segments`}
          {focus ? (
            <span className="ml-3 hidden text-slate sm:inline">· focus: {focus}</span>
          ) : null}
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-6 px-6 py-8">
        {error ? (
          <p className="rounded-xl bg-red-950/50 px-4 py-3 text-sm text-red-200 ring-1 ring-red-500/30">
            {error}
          </p>
        ) : null}

        <section>{projectId ? <VideoPlayer ref={playerRef} src={videoUrl(projectId)} /> : null}</section>

        <section>
          {loading ? (
            <div className="rounded-xl bg-panel-2 px-4 py-8 text-center text-sm text-slate ring-1 ring-white/10">
              Loading timeline…
            </div>
          ) : (
            <Timeline
              segments={segments}
              targetMinutes={targetMinutes}
              onChange={setSegments}
              onSeek={(t) => playerRef.current?.seek(t)}
              onSave={() => void onSave()}
              onExport={openExportModal}
              saving={saving}
              exporting={exporting}
              saveMessage={saveMessage}
            />
          )}
        </section>
      </main>

      <ExportModal
        open={exportOpen}
        phase={exportPhase}
        cleanAudio={cleanAudio}
        onCleanAudioChange={setCleanAudio}
        progress={exportProgress}
        step={exportStep}
        message={exportMessage}
        error={exportError}
        downloadUrl={projectId ? exportDownloadUrl(projectId) : '#'}
        onStart={() => void startExport()}
        onClose={() => {
          if (exporting) return
          setExportOpen(false)
        }}
      />
    </div>
  )
}
