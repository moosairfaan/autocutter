export type ProgressEvent = {
  event: 'progress' | 'done' | 'complete' | 'error'
  status?: 'done' | 'error' | string
  step: string
  progress: number
  message?: string
  project_id?: string
  kept_count?: number
  cut_count?: number
  segment_count?: number
}

export type ScoredSegment = {
  id: number
  start: number
  end: number
  text: string
  score?: number
  reason?: string
  tag?: string
  on_theme?: boolean
}

/** Client-side edit segment (prep for drag/reorder + trim UI). */
export type EditSegment = {
  id: number
  keep: boolean
  /** Position in the final timeline (independent of source chronology). */
  order: number
  /** Inclusive trim in, seconds — defaults to original start. */
  trimStart: number
  /** Exclusive-ish trim out, seconds — defaults to original end. */
  trimEnd: number
  /** Original source bounds (immutable reference for clamp). */
  start: number
  end: number
  text?: string
  score?: number | null
  tag?: string | null
  on_theme?: boolean | null
}

/** Shape stored by / returned from the API (snake_case trims). */
export type ApiEditSegment = {
  id: number
  keep: boolean
  order: number
  trim_in: number
  trim_out: number
  start?: number
  end?: number
  text?: string
  score?: number | null
  tag?: string | null
  on_theme?: boolean | null
  /** Optional camelCase if a newer client wrote them. */
  trimStart?: number
  trimEnd?: number
}

export type SegmentsResponse = {
  project_id: string
  scored:
    | ScoredSegment[]
    | {
        focus: string | null
        segments: ScoredSegment[]
      }
  edit_decision: { segments: ApiEditSegment[] } | null
  meta: Record<string, unknown>
}

export type ProcessOptions = {
  focus?: string | null
  target_minutes?: number | null
  model?: string
  force?: boolean
}
