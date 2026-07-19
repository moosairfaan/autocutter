export type ProgressEvent = {
  event: 'progress' | 'done' | 'error'
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

export type EditSegment = {
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
}

export type SegmentsResponse = {
  project_id: string
  scored:
    | ScoredSegment[]
    | {
        focus: string | null
        segments: ScoredSegment[]
      }
  edit_decision: { segments: EditSegment[] } | null
  meta: Record<string, unknown>
}

export type ProcessOptions = {
  focus?: string | null
  target_minutes?: number | null
  model?: string
  force?: boolean
}
