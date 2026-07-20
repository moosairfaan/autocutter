import type { ApiEditSegment, EditSegment, ScoredSegment } from '../types'

const MIN_TRIM = 0.3

/** Initialize edit segments from scored transcript (first load). */
export function scoredToEditDecision(scored: ScoredSegment[]): EditSegment[] {
  const chronological = [...scored].sort((a, b) => a.start - b.start)
  const keptIds = new Set(
    chronological.filter((s) => (s.score ?? 0) >= 4).map((s) => s.id),
  )

  return chronological.map((s, index) => {
    const keep = keptIds.has(s.id)
    return {
      id: s.id,
      keep,
      // Original chronological index — later reorder UI can change this.
      order: index,
      trimStart: s.start,
      trimEnd: s.end,
      start: s.start,
      end: s.end,
      text: s.text,
      score: s.score ?? null,
      tag: s.tag ?? null,
      on_theme: s.on_theme ?? false,
    }
  })
}

function resolveTrims(
  e: ApiEditSegment | EditSegment,
  start: number,
  end: number,
): { trimStart: number; trimEnd: number } {
  const rawStart =
    'trimStart' in e && typeof e.trimStart === 'number'
      ? e.trimStart
      : 'trim_in' in e && typeof (e as ApiEditSegment).trim_in === 'number'
        ? (e as ApiEditSegment).trim_in
        : start
  const rawEnd =
    'trimEnd' in e && typeof e.trimEnd === 'number'
      ? e.trimEnd
      : 'trim_out' in e && typeof (e as ApiEditSegment).trim_out === 'number'
        ? (e as ApiEditSegment).trim_out
        : end
  return {
    trimStart: clamp(rawStart, start, end - MIN_TRIM),
    trimEnd: clamp(rawEnd, start + MIN_TRIM, end),
  }
}

/** Merge API edit_decision with scored originals into client EditSegment[]. */
export function mergeEditWithScored(
  edit: ApiEditSegment[] | EditSegment[] | null,
  scored: ScoredSegment[],
): EditSegment[] {
  if (!edit?.length) return scoredToEditDecision(scored)
  const byId = new Map(scored.map((s) => [s.id, s]))

  return edit.map((e, index) => {
    const src = byId.get(e.id)
    const start = e.start ?? src?.start ?? 0
    const end = e.end ?? src?.end ?? start + MIN_TRIM
    const { trimStart, trimEnd } = resolveTrims(e, start, end)
    return {
      id: e.id,
      keep: e.keep,
      order: typeof e.order === 'number' ? e.order : index,
      trimStart,
      trimEnd,
      start,
      end,
      text: e.text ?? src?.text,
      score: e.score ?? src?.score ?? null,
      tag: e.tag ?? src?.tag ?? null,
      on_theme: e.on_theme ?? src?.on_theme ?? false,
    }
  })
}

export function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n))
}

export function segmentDuration(seg: EditSegment): number {
  return Math.max(0, seg.trimEnd - seg.trimStart)
}

export function keptDurationSeconds(segments: EditSegment[]): number {
  return segments.filter((s) => s.keep).reduce((sum, s) => sum + segmentDuration(s), 0)
}

/** Kept segments only, sorted by timeline `order` (not source chronology). */
export function getKeptSegmentsInOrder(segments: EditSegment[]): EditSegment[] {
  return segments
    .filter((s) => s.keep)
    .sort((a, b) => a.order - b.order || a.trimStart - b.trimStart)
}

/**
 * Build the edit decision for Save & Export.
 * Uses each segment's trimStart/trimEnd and preserves `order` for sequencing
 * (no longer forces chronological order or resets trims to original bounds).
 */
export function buildSimpleEditDecision(segments: EditSegment[]): EditSegment[] {
  const kept = getKeptSegmentsInOrder(segments)
  const orderById = new Map(kept.map((s, i) => [s.id, i]))

  return segments.map((s) => {
    const start = s.start
    const end = s.end
    const trimStart = clamp(s.trimStart, start, end - MIN_TRIM)
    const trimEnd = clamp(s.trimEnd, trimStart + MIN_TRIM, end)
    return {
      ...s,
      start,
      end,
      trimStart,
      trimEnd,
      order: s.keep ? (orderById.get(s.id) ?? s.order) : -1,
    }
  })
}

/** Map client segments → API edit_decision.json shape (trim_in / trim_out). */
export function toApiEditDecision(segments: EditSegment[]): ApiEditSegment[] {
  return buildSimpleEditDecision(segments).map((s) => ({
    id: s.id,
    keep: s.keep,
    order: s.order,
    trim_in: s.trimStart,
    trim_out: s.trimEnd,
    start: s.start,
    end: s.end,
    text: s.text,
    score: s.score,
    tag: s.tag,
    on_theme: s.on_theme,
  }))
}

export function reindexKeptOrder(segments: EditSegment[]): EditSegment[] {
  const kept = getKeptSegmentsInOrder(segments)
  const orderById = new Map(kept.map((s, i) => [s.id, i]))
  return segments.map((s) =>
    s.keep ? { ...s, order: orderById.get(s.id) ?? 0 } : { ...s, order: -1 },
  )
}

export function toggleKeep(segments: EditSegment[], id: number): EditSegment[] {
  const next = segments.map((s) => {
    if (s.id !== id) return s
    if (s.keep) return { ...s, keep: false, order: -1 }
    const maxOrder = segments
      .filter((x) => x.keep)
      .reduce((m, x) => Math.max(m, x.order), -1)
    return { ...s, keep: true, order: maxOrder + 1 }
  })
  return reindexKeptOrder(next)
}

export function reorderKept(
  segments: EditSegment[],
  activeId: number,
  overId: number,
): EditSegment[] {
  const kept = getKeptSegmentsInOrder(segments)
  const oldIndex = kept.findIndex((s) => s.id === activeId)
  const newIndex = kept.findIndex((s) => s.id === overId)
  if (oldIndex < 0 || newIndex < 0 || oldIndex === newIndex) return segments

  const reordered = [...kept]
  const [moved] = reordered.splice(oldIndex, 1)
  reordered.splice(newIndex, 0, moved)
  const orderById = new Map(reordered.map((s, i) => [s.id, i]))

  return segments.map((s) =>
    s.keep && orderById.has(s.id) ? { ...s, order: orderById.get(s.id)! } : s,
  )
}

export function trimSegment(
  segments: EditSegment[],
  id: number,
  edge: 'in' | 'out',
  nextValue: number,
): EditSegment[] {
  return segments.map((s) => {
    if (s.id !== id) return s
    if (edge === 'in') {
      const trimStart = clamp(nextValue, s.start, s.trimEnd - MIN_TRIM)
      return { ...s, trimStart }
    }
    const trimEnd = clamp(nextValue, s.trimStart + MIN_TRIM, s.end)
    return { ...s, trimEnd }
  })
}

export { MIN_TRIM }
