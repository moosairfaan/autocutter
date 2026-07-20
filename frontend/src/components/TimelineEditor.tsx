import {
  DndContext,
  DragOverlay,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type DragEndEvent,
  type DragStartEvent,
} from '@dnd-kit/core'
import {
  SortableContext,
  horizontalListSortingStrategy,
  useSortable,
} from '@dnd-kit/sortable'
import { CSS } from '@dnd-kit/utilities'
import {
  useMemo,
  useRef,
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { formatTimecode } from '../lib/time'
import {
  getKeptSegmentsInOrder,
  keptDurationSeconds,
  reorderKept,
  segmentDuration,
  toggleKeep,
  trimSegment,
} from '../lib/segments'
import type { EditSegment } from '../types'

const PPS = 12 // pixels per second of trimmed duration
const MIN_WIDTH = 64

type TrimEdge = 'in' | 'out'

type Props = {
  segments: EditSegment[]
  targetMinutes: number | null
  onChange: (next: EditSegment[]) => void
  onSeek: (time: number) => void
  onSaveAndExport: () => void
  exporting?: boolean
}

function previewText(text: string | undefined, words = 8): string {
  if (!text?.trim()) return '—'
  const parts = text.trim().split(/\s+/)
  if (parts.length <= words) return parts.join(' ')
  return `${parts.slice(0, words).join(' ')}…`
}

function formatMinutes(seconds: number): string {
  return `${(seconds / 60).toFixed(1)} min`
}

function blockClasses(seg: EditSegment): string {
  const score = seg.score ?? 5
  if (score >= 7) return 'bg-emerald-600/90 text-emerald-50 ring-emerald-400/40'
  if (score >= 4) return 'bg-amber-500/90 text-amber-950 ring-amber-300/40'
  return 'bg-red-600/80 text-red-50 ring-red-400/40'
}

function TimelineBlock({
  seg,
  sortable,
  isDragging,
  dragHandleProps,
  setNodeRef,
  style,
  onSeek,
  onCut,
  onTrimMove,
  onTrimRelease,
  trimTooltip,
}: {
  seg: EditSegment
  sortable?: boolean
  isDragging?: boolean
  /** dnd-kit listeners — attach only to the block body, not trim handles */
  dragHandleProps?: Record<string, unknown>
  setNodeRef?: (node: HTMLElement | null) => void
  style?: CSSProperties
  onSeek: () => void
  onCut?: () => void
  onTrimMove?: (edge: TrimEdge, next: number) => void
  onTrimRelease?: (edge: TrimEdge) => void
  trimTooltip?: { edge: TrimEdge; time: number } | null
}) {
  const width = Math.max(segmentDuration(seg) * PPS, MIN_WIDTH)

  const startTrim = (edge: TrimEdge, e: ReactPointerEvent<HTMLButtonElement>) => {
    if (!onTrimMove || !onTrimRelease) return
    e.preventDefault()
    e.stopPropagation()
    const startX = e.clientX
    const startValue = edge === 'in' ? seg.trimStart : seg.trimEnd
    const target = e.currentTarget
    target.setPointerCapture(e.pointerId)

    const onMove = (ev: PointerEvent) => {
      const dt = (ev.clientX - startX) / PPS
      onTrimMove(edge, startValue + dt)
    }
    const onUp = (ev: PointerEvent) => {
      try {
        target.releasePointerCapture(ev.pointerId)
      } catch {
        /* already released */
      }
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
      const dt = (ev.clientX - startX) / PPS
      onTrimMove(edge, startValue + dt)
      onTrimRelease(edge)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  return (
    <div
      ref={setNodeRef}
      style={{ ...style, width }}
      className={[
        'relative flex h-[4.5rem] shrink-0 select-none flex-col justify-between overflow-visible rounded-md ring-1 transition',
        blockClasses(seg),
        seg.on_theme ? 'outline outline-2 outline-offset-1 outline-cyan-300' : '',
        isDragging ? 'opacity-40' : '',
      ].join(' ')}
      title={`#${seg.id} · ${formatTimecode(seg.trimStart)}–${formatTimecode(seg.trimEnd)}\n${seg.text ?? ''}`}
    >
      {onTrimMove ? (
        <>
          <button
            type="button"
            data-trim="in"
            aria-label="Trim start"
            className="absolute inset-y-0 left-0 z-20 w-2.5 cursor-ew-resize rounded-l-md bg-black/35 hover:bg-white/50"
            onPointerDown={(e) => startTrim('in', e)}
            onClick={(e) => e.stopPropagation()}
          />
          <button
            type="button"
            data-trim="out"
            aria-label="Trim end"
            className="absolute inset-y-0 right-0 z-20 w-2.5 cursor-ew-resize rounded-r-md bg-black/35 hover:bg-white/50"
            onPointerDown={(e) => startTrim('out', e)}
            onClick={(e) => e.stopPropagation()}
          />
        </>
      ) : null}

      {trimTooltip ? (
        <div
          className={[
            'pointer-events-none absolute -top-7 z-30 rounded bg-ink px-1.5 py-0.5 font-mono text-[10px] text-paper shadow ring-1 ring-white/20',
            trimTooltip.edge === 'in' ? 'left-0' : 'right-0',
          ].join(' ')}
        >
          {formatTimecode(trimTooltip.time)}
        </div>
      ) : null}

      {/* Reorder / seek zone — center body only */}
      <div
        className={[
          'flex h-full flex-col justify-between px-3 py-1.5',
          sortable ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer',
        ].join(' ')}
        onClick={onSeek}
        {...(sortable ? dragHandleProps : {})}
      >
        <div className="flex items-center justify-between gap-1 text-[10px] font-mono opacity-90">
          <span>#{seg.id}</span>
          <span>{formatTimecode(segmentDuration(seg))}</span>
        </div>
        <p className="line-clamp-2 text-[11px] leading-snug opacity-95">
          {previewText(seg.text)}
        </p>
      </div>

      {onCut ? (
        <button
          type="button"
          className="absolute right-3 top-1 z-10 rounded bg-black/30 px-1 text-[10px] hover:bg-black/50"
          onClick={(e) => {
            e.stopPropagation()
            onCut()
          }}
          onPointerDown={(e) => e.stopPropagation()}
          aria-label="Cut segment"
        >
          ✕
        </button>
      ) : null}
    </div>
  )
}

function SortableKeptBlock({
  seg,
  onSeek,
  onCut,
  onTrimMove,
  onTrimRelease,
  trimTooltip,
}: {
  seg: EditSegment
  onSeek: () => void
  onCut: () => void
  onTrimMove: (edge: TrimEdge, next: number) => void
  onTrimRelease: (edge: TrimEdge) => void
  trimTooltip: { edge: TrimEdge; time: number } | null
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: seg.id })

  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  return (
    <TimelineBlock
      seg={seg}
      sortable
      isDragging={isDragging}
      setNodeRef={setNodeRef}
      style={style}
      dragHandleProps={{ ...attributes, ...listeners }}
      onSeek={onSeek}
      onCut={onCut}
      onTrimMove={onTrimMove}
      onTrimRelease={onTrimRelease}
      trimTooltip={trimTooltip}
    />
  )
}

export function TimelineEditor({
  segments,
  targetMinutes,
  onChange,
  onSeek,
  onSaveAndExport,
  exporting,
}: Props) {
  const [activeId, setActiveId] = useState<number | null>(null)
  const [cutOpen, setCutOpen] = useState(false)
  const [trimming, setTrimming] = useState<{
    id: number
    edge: TrimEdge
    time: number
  } | null>(null)

  // Keep latest segments for pointer handlers without waiting on re-render.
  const segmentsRef = useRef(segments)
  segmentsRef.current = segments

  const kept = useMemo(() => getKeptSegmentsInOrder(segments), [segments])
  const cut = useMemo(
    () =>
      segments
        .filter((s) => !s.keep)
        .sort((a, b) => a.start - b.start),
    [segments],
  )

  const keptSeconds = keptDurationSeconds(segments)
  const targetSeconds = targetMinutes != null ? targetMinutes * 60 : null
  const overTarget =
    targetSeconds != null ? keptSeconds > targetSeconds + 0.5 : false

  const sensors = useSensors(
    useSensor(PointerSensor, {
      // Allow clicks (seek) without starting a drag.
      activationConstraint: { distance: 6 },
    }),
  )

  const activeSeg =
    activeId != null ? segments.find((s) => s.id === activeId) ?? null : null

  const onDragStart = (event: DragStartEvent) => {
    setActiveId(Number(event.active.id))
  }

  const onDragEnd = (event: DragEndEvent) => {
    setActiveId(null)
    const { active, over } = event
    if (!over || active.id === over.id) return
    onChange(reorderKept(segments, Number(active.id), Number(over.id)))
  }

  const handleTrimMove = (id: number, edge: TrimEdge, next: number) => {
    const updated = trimSegment(segmentsRef.current, id, edge, next)
    segmentsRef.current = updated
    const seg = updated.find((s) => s.id === id)
    if (!seg) return
    const time = edge === 'in' ? seg.trimStart : seg.trimEnd
    setTrimming({ id, edge, time })
    onChange(updated)
  }

  const handleTrimRelease = (id: number, edge: TrimEdge) => {
    const seg = segmentsRef.current.find((s) => s.id === id)
    setTrimming(null)
    if (!seg) return
    onSeek(edge === 'in' ? seg.trimStart : seg.trimEnd)
  }

  return (
    <div className="space-y-4 rounded-xl bg-panel-2 p-4 ring-1 ring-white/10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-base font-bold text-white">Timeline</h2>
          <p className="mt-0.5 font-mono text-sm text-mist">
            Kept:{' '}
            <span className={overTarget ? 'text-amber-300' : 'text-ok'}>
              {formatMinutes(keptSeconds)}
            </span>
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
              {kept.length} kept · {cut.length} cut
            </span>
          </p>
        </div>
        <button
          type="button"
          onClick={onSaveAndExport}
          disabled={exporting || kept.length === 0}
          className="rounded-lg bg-accent px-4 py-2 font-display text-sm font-bold text-white transition hover:bg-accent-dim disabled:opacity-50"
        >
          {exporting ? 'Exporting…' : 'Save & Export'}
        </button>
      </div>

      <p className="text-[11px] text-slate">
        Drag body to reorder · drag edges to trim · click to seek · ✕ to cut
      </p>

      <div>
        <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate">
          Kept (edit order)
        </p>
        <div className="overflow-x-auto overflow-y-visible pb-2 pt-7">
          <DndContext
            sensors={sensors}
            collisionDetection={closestCenter}
            onDragStart={onDragStart}
            onDragEnd={onDragEnd}
            onDragCancel={() => setActiveId(null)}
          >
            <SortableContext
              items={kept.map((s) => s.id)}
              strategy={horizontalListSortingStrategy}
            >
              <div className="flex min-h-[4.5rem] min-w-min gap-1">
                {kept.length === 0 ? (
                  <p className="py-6 text-sm text-slate">
                    No kept segments — restore one from the cut list below.
                  </p>
                ) : (
                  kept.map((seg) => (
                    <SortableKeptBlock
                      key={seg.id}
                      seg={seg}
                      onSeek={() => onSeek(seg.trimStart)}
                      onCut={() => onChange(toggleKeep(segments, seg.id))}
                      onTrimMove={(edge, next) =>
                        handleTrimMove(seg.id, edge, next)
                      }
                      onTrimRelease={(edge) =>
                        handleTrimRelease(seg.id, edge)
                      }
                      trimTooltip={
                        trimming?.id === seg.id
                          ? { edge: trimming.edge, time: trimming.time }
                          : null
                      }
                    />
                  ))
                )}
              </div>
            </SortableContext>
            <DragOverlay>
              {activeSeg ? (
                <TimelineBlock
                  seg={activeSeg}
                  onSeek={() => undefined}
                />
              ) : null}
            </DragOverlay>
          </DndContext>
        </div>
      </div>

      {cut.length > 0 ? (
        <div className="rounded-lg bg-panel/60 ring-1 ring-white/5">
          <button
            type="button"
            className="flex w-full items-center justify-between px-3 py-2 text-left text-sm text-mist hover:text-white"
            onClick={() => setCutOpen((o) => !o)}
            aria-expanded={cutOpen}
          >
            <span>
              Cut <span className="text-slate">({cut.length})</span>
            </span>
            <span className="font-mono text-xs text-slate">
              {cutOpen ? '▾' : '▸'}
            </span>
          </button>
          {cutOpen ? (
            <ul className="max-h-48 space-y-1 overflow-y-auto border-t border-white/5 px-2 py-2">
              {cut.map((seg) => (
                <li key={seg.id}>
                  <div className="flex items-start gap-2 rounded-md px-2 py-1.5 hover:bg-white/5">
                    <button
                      type="button"
                      className="mt-0.5 shrink-0 rounded bg-ok/20 px-2 py-0.5 text-[11px] font-medium text-ok hover:bg-ok/30"
                      onClick={() => onChange(toggleKeep(segments, seg.id))}
                    >
                      Keep
                    </button>
                    <button
                      type="button"
                      className="min-w-0 flex-1 text-left"
                      onClick={() => onSeek(seg.trimStart)}
                    >
                      <div className="font-mono text-[11px] text-slate">
                        #{seg.id} · {formatTimecode(seg.trimStart)}–
                        {formatTimecode(seg.trimEnd)}
                        {seg.tag ? ` · ${seg.tag}` : ''}
                      </div>
                      <p className="truncate text-xs text-mist">
                        {previewText(seg.text, 12)}
                      </p>
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          ) : null}
        </div>
      ) : null}
    </div>
  )
}
