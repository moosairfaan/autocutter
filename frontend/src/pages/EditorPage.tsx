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
import { ExportModal, type ExportResolution } from '../components/ExportModal'
import { TimelineEditor } from '../components/TimelineEditor'
import { VideoPlayer, type VideoPlayerHandle } from '../components/VideoPlayer'
import { mergeEditWithScored, toApiEditDecision } from '../lib/segments'
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

  const [exportOpen, setExportOpen] = useState(false)
  const [exportPhase, setExportPhase] = useState<
    'options' | 'running' | 'done' | 'error'
  >('options')
  const [cleanAudio, setCleanAudio] = useState(false)
  const [resolution, setResolution] = useState<ExportResolution>('original')
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

  const openSaveAndExport = () => {
    if (exporting) return
    setExportOpen(true)
    setExportPhase('options')
    setCleanAudio(false)
    setResolution('original')
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
    setExportMessage('Saving keep/cut decisions…')

    const apiPayload = toApiEditDecision(segments)
    // Keep local state in sync with what we persist (order + clamps).
    setSegments(mergeEditWithScored(apiPayload, scoredSegments))

    try {
      await patchSegments(projectId, apiPayload)
      setExportStep('export')
      setExportMessage('Starting export…')
      await exportProject(
        projectId,
        (evt) => {
          setExportProgress(evt.progress)
          setExportStep(evt.step)
          setExportMessage(evt.message ?? '')
        },
        { clean_audio: cleanAudio, resolution },
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
    <div className="min-h-screen bg-panel text-ink">
      <header className="sticky top-0 z-40 flex items-center justify-between gap-4 border-b border-white/10 bg-panel/90 px-6 py-4 backdrop-blur-md">
        <div className="flex min-w-0 items-center gap-4">
          <Link
            to="/"
            className="shrink-0 font-display text-lg font-bold tracking-tight text-accent transition hover:text-white"
          >
            autocutter
          </Link>
          <span className="truncate font-mono text-xs text-slate">{projectId}</span>
        </div>
        <div className="shrink-0 text-sm text-slate">
          {loading
            ? 'Loading segments…'
            : `${scoredSegments.length} segments`}
          {focus ? (
            <span className="ml-3 hidden text-slate/80 sm:inline">· focus: {focus}</span>
          ) : null}
        </div>
      </header>

      <main className="mx-auto flex max-w-6xl flex-col gap-8 px-6 py-8">
        {error ? (
          <p className="rounded-2xl bg-cut/10 px-4 py-3 text-sm text-cut ring-1 ring-cut/30">
            {error}
          </p>
        ) : null}

        <section className="rounded-2xl bg-panel-2 p-4 shadow-lg shadow-black/30 ring-1 ring-white/10 sm:p-5">
          {projectId ? <VideoPlayer ref={playerRef} src={videoUrl(projectId)} /> : null}
        </section>

        <section>
          {loading ? (
            <div className="rounded-2xl bg-panel-2 px-6 py-12 text-center text-sm text-slate shadow-lg shadow-black/30 ring-1 ring-white/10">
              Loading timeline…
            </div>
          ) : (
            <TimelineEditor
              segments={segments}
              targetMinutes={targetMinutes}
              onChange={setSegments}
              onSeek={(t) => playerRef.current?.seek(t)}
              onSaveAndExport={openSaveAndExport}
              exporting={exporting}
            />
          )}
        </section>
      </main>

      <ExportModal
        open={exportOpen}
        phase={exportPhase}
        cleanAudio={cleanAudio}
        onCleanAudioChange={setCleanAudio}
        resolution={resolution}
        onResolutionChange={setResolution}
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
