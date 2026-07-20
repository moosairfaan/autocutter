import { useMemo } from 'react'
import { formatTimecode } from '../lib/time'
import { toggleKeep } from '../lib/segments'
import type { EditSegment } from '../types'

type Props = {
  segments: EditSegment[]
  targetMinutes: number | null
  onChange: (next: EditSegment[]) => void
  onSeek: (time: number) => void
  onSaveAndExport: () => void
  exporting?: boolean
}

function previewText(text: string | undefined, words = 10): string {
  if (!text?.trim()) return '—'
  const parts = text.trim().split(/\s+/)
  if (parts.length <= words) return parts.join(' ')
  return `${parts.slice(0, words).join(' ')}…`
}

function formatMinutes(seconds: number): string {
  const mins = seconds / 60
  return `${mins.toFixed(1)} min`
}

export function SegmentList({
  segments,
  targetMinutes,
  onChange,
  onSeek,
  onSaveAndExport,
  exporting,
}: Props) {
  const chronological = useMemo(
    () =>
      [...segments].sort(
        (a, b) => (a.start ?? a.trim_in) - (b.start ?? b.trim_in),
      ),
    [segments],
  )

  const keptSeconds = chronological
    .filter((s) => s.keep)
    .reduce((sum, s) => {
      const start = s.start ?? s.trim_in
      const end = s.end ?? s.trim_out
      return sum + Math.max(0, end - start)
    }, 0)
  const targetSeconds = targetMinutes != null ? targetMinutes * 60 : null
  const keptCount = chronological.filter((s) => s.keep).length

  return (
    <div className="space-y-4 rounded-xl bg-panel-2 p-4 ring-1 ring-white/10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-base font-bold text-white">Segments</h2>
          <p className="mt-0.5 font-mono text-sm text-mist">
            Kept:{' '}
            <span className="text-ok">{formatMinutes(keptSeconds)}</span>
            {targetSeconds != null ? (
              <>
                {' '}
                / Target:{' '}
                <span className="text-white">{formatMinutes(targetSeconds)}</span>
              </>
            ) : (
              <span className="text-slate"> / Target: —</span>
            )}
            <span className="ml-3 text-slate">
              {keptCount} kept · {chronological.length - keptCount} cut
            </span>
          </p>
        </div>
        <button
          type="button"
          onClick={onSaveAndExport}
          disabled={exporting || keptCount === 0}
          className="rounded-lg bg-accent px-4 py-2 font-display text-sm font-bold text-white transition hover:bg-accent-dim disabled:opacity-50"
        >
          {exporting ? 'Exporting…' : 'Save & Export'}
        </button>
      </div>

      <ul className="max-h-[55vh] space-y-1.5 overflow-y-auto pr-1">
        {chronological.map((seg) => {
          const start = seg.start ?? seg.trim_in
          const end = seg.end ?? seg.trim_out
          return (
            <li key={seg.id}>
              <div
                role="button"
                tabIndex={0}
                onClick={() => onSeek(start)}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault()
                    onSeek(start)
                  }
                }}
                className={[
                  'flex cursor-pointer items-start gap-3 rounded-lg px-3 py-2.5 ring-1 transition',
                  seg.keep
                    ? 'bg-panel ring-white/10 hover:ring-white/25'
                    : 'bg-panel/40 ring-white/5 opacity-70 hover:opacity-90',
                ].join(' ')}
              >
                <label
                  className="flex shrink-0 items-center pt-0.5"
                  onClick={(e) => e.stopPropagation()}
                  onKeyDown={(e) => e.stopPropagation()}
                >
                  <input
                    type="checkbox"
                    checked={seg.keep}
                    onChange={() => onChange(toggleKeep(segments, seg.id))}
                    className="h-4 w-4 accent-ok"
                    aria-label={seg.keep ? 'Keep segment' : 'Cut segment'}
                  />
                </label>

                <div className="min-w-0 flex-1">
                  <div className="flex flex-wrap items-center gap-x-2 gap-y-1 font-mono text-[11px] text-slate">
                    <span className="text-mist">
                      {formatTimecode(start)}–{formatTimecode(end)}
                    </span>
                    <span>·</span>
                    <span>score {seg.score ?? '—'}</span>
                    {seg.tag ? (
                      <>
                        <span>·</span>
                        <span className="rounded bg-white/10 px-1.5 py-0.5 text-mist">
                          {seg.tag}
                        </span>
                      </>
                    ) : null}
                    {seg.on_theme ? (
                      <span className="rounded bg-cyan-500/20 px-1.5 py-0.5 text-cyan-200">
                        on theme
                      </span>
                    ) : null}
                    <span className="text-slate/70">#{seg.id}</span>
                  </div>
                  <p className="mt-1 text-sm leading-snug text-paper/90">
                    {previewText(seg.text)}
                  </p>
                </div>
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}
