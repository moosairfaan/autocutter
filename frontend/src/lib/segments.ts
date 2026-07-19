import type { EditSegment, ScoredSegment } from '../types'

const MIN_TRIM = 0.05

export function scoredToEditDecision(scored: ScoredSegment[]): EditSegment[] {
  const keptIds = new Set(
    scored.filter((s) => (s.score ?? 0) >= 4).map((s) => s.id),
  )
  const keptChrono = scored
    .filter((s) => keptIds.has(s.id))
    .sort((a, b) => a.start - b.start)
  const orderById = new Map(keptChrono.map((s, i) => [s.id, i]))

  return scored.map((s) => {
    const keep = keptIds.has(s.id)
    return {
      id: s.id,
      keep,
      order: keep ? (orderById.get(s.id) ?? 0) : -1,
      trim_in: s.start,
      trim_out: s.end,
      start: s.start,
      end: s.end,
      text: s.text,
      score: s.score ?? null,
      tag: s.tag ?? null,
      on_theme: s.on_theme ?? false,
    }
  })
}

/** Merge edit decision with scored originals so start/end/score stay available. */
export function mergeEditWithScored(
  edit: EditSegment[] | null,
  scored: ScoredSegment[],
): EditSegment[] {
  if (!edit?.length) return scoredToEditDecision(scored)
  const byId = new Map(scored.map((s) => [s.id, s]))
  return edit.map((e) => {
    const src = byId.get(e.id)
    const start = e.start ?? src?.start ?? e.trim_in
    const end = e.end ?? src?.end ?? e.trim_out
    return {
      ...e,
      start,
      end,
      text: e.text ?? src?.text,
      score: e.score ?? src?.score ?? null,
      tag: e.tag ?? src?.tag ?? null,
      on_theme: e.on_theme ?? src?.on_theme ?? false,
      trim_in: clamp(e.trim_in, start, end - MIN_TRIM),
      trim_out: clamp(e.trim_out, start + MIN_TRIM, end),
    }
  })
}

export function clamp(n: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, n))
}

export function segmentDuration(seg: EditSegment): number {
  return Math.max(0, seg.trim_out - seg.trim_in)
}

export function keptDurationSeconds(segments: EditSegment[]): number {
  return segments.filter((s) => s.keep).reduce((sum, s) => sum + segmentDuration(s), 0)
}

export function reindexKeptOrder(segments: EditSegment[]): EditSegment[] {
  const kept = segments
    .filter((s) => s.keep)
    .sort((a, b) => a.order - b.order || a.trim_in - b.trim_in)
  const orderById = new Map(kept.map((s, i) => [s.id, i]))
  return segments.map((s) =>
    s.keep ? { ...s, order: orderById.get(s.id) ?? 0 } : { ...s, order: -1 },
  )
}

export function toggleKeep(segments: EditSegment[], id: number): EditSegment[] {
  const next = segments.map((s) => {
    if (s.id !== id) return s
    if (s.keep) return { ...s, keep: false, order: -1 }
    const maxOrder = segments.filter((x) => x.keep).reduce((m, x) => Math.max(m, x.order), -1)
    return { ...s, keep: true, order: maxOrder + 1 }
  })
  return reindexKeptOrder(next)
}

export function reorderKept(
  segments: EditSegment[],
  activeId: number,
  overId: number,
): EditSegment[] {
  const kept = segments
    .filter((s) => s.keep)
    .sort((a, b) => a.order - b.order)
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
    const origStart = s.start ?? s.trim_in
    const origEnd = s.end ?? s.trim_out
    if (edge === 'in') {
      const trim_in = clamp(nextValue, origStart, s.trim_out - MIN_TRIM)
      return { ...s, trim_in }
    }
    const trim_out = clamp(nextValue, s.trim_in + MIN_TRIM, origEnd)
    return { ...s, trim_out }
  })
}

export { MIN_TRIM }
