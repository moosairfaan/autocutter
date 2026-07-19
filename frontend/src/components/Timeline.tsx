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
  useState,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from 'react'
import { formatTimecode } from '../lib/time'
import {
  keptDurationSeconds,
  reorderKept,
  segmentDuration,
  toggleKeep,
  trimSegment,
} from '../lib/segments'
import type { EditSegment } from '../types'

const PPS = 10 // pixels per second
const MIN_WIDTH = 56

type Props = {
  segments: EditSegment[]
  targetMinutes: number | null
  onChange: (next: EditSegment[]) => void
  onSeek: (time: number) => void
  onSave: () => void
  onExport: () => void
  saving?: boolean
  exporting?: boolean
  saveMessage?: string | null
}

function blockClasses(seg: EditSegment): string {
  const score = seg.score ?? 5
  let base: string
  if (!seg.keep) {
    base = 'bg-red-700/80 text-red-50 ring-red-500/40'
  } else if (score >= 7) {
    base = 'bg-emerald-600/90 text-emerald-50 ring-emerald-400/50'
  } else if (score >= 4) {
    base = 'bg-amber-500/90 text-amber-950 ring-amber-300/50'
  } else {
    base = 'bg-red-600/80 text-red-50 ring-red-400/40'
  }
  const theme = seg.on_theme
    ? 'outline outline-2 outline-offset-1 outline-cyan-300 shadow-[0_0_0_1px_rgba(103,232,249,0.5)]'
    : ''
  return `${base} ${theme}`
}

function SegmentBlock({
  seg,
  sortable,
  isDragging,
  dragHandleProps,
  setNodeRef,
  style,
  onToggleSeek,
  onTrim,
}: {
  seg: EditSegment
  sortable: boolean
  isDragging?: boolean
  dragHandleProps?: Record<string, unknown>
  setNodeRef?: (node: HTMLElement | null) => void
  style?: CSSProperties
  onToggleSeek: () => void
  onTrim: (edge: 'in' | 'out', clientX: number, startValue: number) => void
}) {
  const width = Math.max(segmentDuration(seg) * PPS, MIN_WIDTH)

  const startTrim = (edge: 'in' | 'out', e: ReactPointerEvent) => {
    e.preventDefault()
    e.stopPropagation()
    const startX = e.clientX
    const startValue = edge === 'in' ? seg.trim_in : seg.trim_out
    const target = e.currentTarget
    target.setPointerCapture(e.pointerId)

    const onMove = (ev: PointerEvent) => {
      const dt = (ev.clientX - startX) / PPS
      onTrim(edge, ev.clientX, startValue + dt)
    }
    const onUp = (ev: PointerEvent) => {
      target.releasePointerCapture(ev.pointerId)
      window.removeEventListener('pointermove', onMove)
      window.removeEventListener('pointerup', onUp)
    }
    window.addEventListener('pointermove', onMove)
    window.addEventListener('pointerup', onUp)
  }

  return (
    <div
      ref={setNodeRef}
      style={{ ...style, width }}
      className={[
        'relative flex h-16 shrink-0 select-none flex-col justify-between overflow-hidden rounded-md px-2 py-1.5 ring-1 transition',
        blockClasses(seg),
        isDragging ? 'opacity-40' : '',
        sortable ? 'cursor-grab active:cursor-grabbing' : 'cursor-pointer',
      ].join(' ')}
      onClick={(e) => {
        // Ignore clicks that originated on trim handles
        if ((e.target as HTMLElement).dataset.trim) return
        onToggleSeek()
      }}
      {...(sortable ? dragHandleProps : {})}
      title={`#${seg.id} · score ${seg.score ?? '—'} · ${seg.keep ? 'kept' : 'cut'}${seg.on_theme ? ' · on theme' : ''}\n${seg.text ?? ''}`}
    >
      <button
        type="button"
        data-trim="in"
        aria-label="Trim in"
        className="absolute inset-y-0 left-0 z-10 w-2 cursor-ew-resize bg-black/25 hover:bg-white/40"
        onPointerDown={(e) => startTrim('in', e)}
        onClick={(e) => e.stopPropagation()}
      />
      <button
        type="button"
        data-trim="out"
        aria-label="Trim out"
        className="absolute inset-y-0 right-0 z-10 w-2 cursor-ew-resize bg-black/25 hover:bg-white/40"
        onPointerDown={(e) => startTrim('out', e)}
        onClick={(e) => e.stopPropagation()}
      />

      <div className="flex items-center justify-between gap-1 pl-1.5 pr-1.5 text-[10px] font-mono opacity-90">
        <span>#{seg.id}</span>
        <span>{formatTimecode(segmentDuration(seg))}</span>
      </div>
      <p className="line-clamp-2 pl-1.5 pr-1.5 text-[11px] leading-snug opacity-95">
        {seg.text || '—'}
      </p>
    </div>
  )
}

function SortableKeptBlock({
  seg,
  onToggleSeek,
  onTrim,
}: {
  seg: EditSegment
  onToggleSeek: () => void
  onTrim: (edge: 'in' | 'out', next: number) => void
}) {
  const { attributes, listeners, setNodeRef, transform, transition, isDragging } =
    useSortable({ id: seg.id })

  const style: CSSProperties = {
    transform: CSS.Transform.toString(transform),
    transition,
  }

  return (
    <SegmentBlock
      seg={seg}
      sortable
      isDragging={isDragging}
      setNodeRef={setNodeRef}
      style={style}
      dragHandleProps={{ ...attributes, ...listeners }}
      onToggleSeek={onToggleSeek}
      onTrim={(edge, _x, next) => onTrim(edge, next)}
    />
  )
}

export function Timeline({
  segments,
  targetMinutes,
  onChange,
  onSeek,
  onSave,
  onExport,
  saving,
  exporting,
  saveMessage,
}: Props) {
  const [activeId, setActiveId] = useState<number | null>(null)

  const kept = useMemo(
    () => segments.filter((s) => s.keep).sort((a, b) => a.order - b.order),
    [segments],
  )
  const cut = useMemo(
    () =>
      segments
        .filter((s) => !s.keep)
        .sort((a, b) => (a.start ?? a.trim_in) - (b.start ?? b.trim_in)),
    [segments],
  )

  const keptSeconds = keptDurationSeconds(segments)
  const targetSeconds = targetMinutes != null ? targetMinutes * 60 : null
  const overTarget =
    targetSeconds != null ? keptSeconds > targetSeconds + 0.5 : false

  const sensors = useSensors(
    useSensor(PointerSensor, {
      activationConstraint: { distance: 6 },
    }),
  )

  const activeSeg = activeId != null ? segments.find((s) => s.id === activeId) : null

  const onDragStart = (event: DragStartEvent) => {
    setActiveId(Number(event.active.id))
  }

  const onDragEnd = (event: DragEndEvent) => {
    setActiveId(null)
    const { active, over } = event
    if (!over || active.id === over.id) return
    onChange(reorderKept(segments, Number(active.id), Number(over.id)))
  }

  const handleToggleSeek = (seg: EditSegment) => {
    onSeek(seg.trim_in)
    onChange(toggleKeep(segments, seg.id))
  }

  return (
    <div className="space-y-3 rounded-xl bg-panel-2 p-4 ring-1 ring-white/10">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="font-display text-base font-bold text-white">Timeline</h2>
          <p className="mt-0.5 font-mono text-sm">
            <span className={overTarget ? 'text-amber-300' : 'text-ok'}>
              {formatTimecode(keptSeconds)}
            </span>
            <span className="text-slate"> kept</span>
            {targetSeconds != null ? (
              <>
                <span className="text-slate"> / </span>
                <span className="text-mist">{formatTimecode(targetSeconds)} target</span>
              </>
            ) : (
              <span className="text-slate"> · no target set</span>
            )}
            <span className="ml-3 text-slate">
              {kept.length} kept · {cut.length} cut
            </span>
          </p>
        </div>
        <div className="flex items-center gap-3">
          {saveMessage ? (
            <span className="text-sm text-mist">{saveMessage}</span>
          ) : null}
          <button
            type="button"
            onClick={onSave}
            disabled={saving || exporting}
            className="rounded-lg bg-white/10 px-4 py-2 font-display text-sm font-bold text-white transition hover:bg-white/15 disabled:opacity-50"
          >
            {saving ? 'Saving…' : 'Save'}
          </button>
          <button
            type="button"
            onClick={onExport}
            disabled={saving || exporting || kept.length === 0}
            className="rounded-lg bg-accent px-4 py-2 font-display text-sm font-bold text-white transition hover:bg-accent-dim disabled:opacity-50"
          >
            {exporting ? 'Exporting…' : 'Export'}
          </button>
        </div>
      </div>

      <div className="flex flex-wrap gap-3 text-[11px] text-slate">
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-emerald-600" /> high / kept
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-amber-500" /> medium
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm bg-red-700" /> cut / low
        </span>
        <span className="inline-flex items-center gap-1.5">
          <span className="h-2.5 w-2.5 rounded-sm outline outline-2 outline-cyan-300" />{' '}
          on theme
        </span>
        <span className="text-slate/80">Click = seek + toggle keep · drag kept to reorder · edges trim</span>
      </div>

      <div>
        <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate">
          Kept (edit order)
        </p>
        <div className="overflow-x-auto pb-2">
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
              <div className="flex min-h-16 min-w-min gap-1">
                {kept.length === 0 ? (
                  <p className="py-4 text-sm text-slate">No kept segments — click a cut clip to restore.</p>
                ) : (
                  kept.map((seg) => (
                    <SortableKeptBlock
                      key={seg.id}
                      seg={seg}
                      onToggleSeek={() => handleToggleSeek(seg)}
                      onTrim={(edge, next) =>
                        onChange(trimSegment(segments, seg.id, edge, next))
                      }
                    />
                  ))
                )}
              </div>
            </SortableContext>
            <DragOverlay>
              {activeSeg ? (
                <SegmentBlock
                  seg={activeSeg}
                  sortable={false}
                  onToggleSeek={() => undefined}
                  onTrim={() => undefined}
                />
              ) : null}
            </DragOverlay>
          </DndContext>
        </div>
      </div>

      {cut.length > 0 ? (
        <div>
          <p className="mb-1.5 text-xs font-medium uppercase tracking-wide text-slate">
            Cut
          </p>
          <div className="overflow-x-auto pb-1">
            <div className="flex min-w-min gap-1">
              {cut.map((seg) => (
                <SegmentBlock
                  key={seg.id}
                  seg={seg}
                  sortable={false}
                  onToggleSeek={() => handleToggleSeek(seg)}
                  onTrim={(edge, _x, next) =>
                    onChange(trimSegment(segments, seg.id, edge, next))
                  }
                />
              ))}
            </div>
          </div>
        </div>
      ) : null}
    </div>
  )
}
