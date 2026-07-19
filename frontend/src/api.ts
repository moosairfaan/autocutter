import type { ProcessOptions, ProgressEvent, SegmentsResponse } from './types'

const API_BASE = '/api'

function parseSseChunk(chunk: string): ProgressEvent | null {
  let data = ''
  for (const line of chunk.split('\n')) {
    if (line.startsWith('data:')) {
      data += line.slice(5).trimStart()
    }
  }
  if (!data) return null
  return JSON.parse(data) as ProgressEvent
}

export async function createProject(file: File): Promise<{ project_id: string }> {
  const form = new FormData()
  form.append('video', file)
  const res = await fetch(`${API_BASE}/projects`, {
    method: 'POST',
    body: form,
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(detail || `Upload failed (${res.status})`)
  }
  return res.json() as Promise<{ project_id: string }>
}

async function readSseProgress(
  res: Response,
  onProgress: (event: ProgressEvent) => void,
  emptyMessage: string,
): Promise<ProgressEvent> {
  if (!res.ok || !res.body) {
    const detail = await res.text()
    throw new Error(detail || emptyMessage)
  }

  const reader = res.body.getReader()
  const decoder = new TextDecoder()
  let buffer = ''
  let last: ProgressEvent | null = null

  while (true) {
    const { done, value } = await reader.read()
    if (done) break
    buffer += decoder.decode(value, { stream: true })
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    for (const part of parts) {
      const evt = parseSseChunk(part)
      if (!evt) continue
      last = evt
      onProgress(evt)
      if (evt.event === 'error') {
        throw new Error(evt.message || emptyMessage)
      }
      if (evt.event === 'done') {
        return evt
      }
    }
  }

  if (last?.event === 'done') return last
  throw new Error(emptyMessage)
}

export async function processProject(
  projectId: string,
  options: ProcessOptions,
  onProgress: (event: ProgressEvent) => void,
  signal?: AbortSignal,
): Promise<ProgressEvent> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/process`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      focus: options.focus || null,
      target_minutes: options.target_minutes ?? null,
      model: options.model ?? 'medium',
      force: options.force ?? false,
    }),
    signal,
  })

  return readSseProgress(res, onProgress, 'Processing ended without a completion event')
}

export async function exportProject(
  projectId: string,
  onProgress: (event: ProgressEvent) => void,
  options: { clean_audio?: boolean } = {},
  signal?: AbortSignal,
): Promise<ProgressEvent> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/export`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      clean_audio: options.clean_audio ?? false,
    }),
    signal,
  })
  return readSseProgress(res, onProgress, 'Export ended without a completion event')
}

export async function fetchSegments(projectId: string): Promise<SegmentsResponse> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/segments`)
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(detail || `Failed to load segments (${res.status})`)
  }
  return res.json() as Promise<SegmentsResponse>
}

export async function patchSegments(
  projectId: string,
  segments: import('./types').EditSegment[],
): Promise<void> {
  const res = await fetch(`${API_BASE}/projects/${projectId}/segments`, {
    method: 'PATCH',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ segments }),
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(detail || `Save failed (${res.status})`)
  }
}

export function videoUrl(projectId: string): string {
  return `${API_BASE}/projects/${projectId}/video`
}

export function exportDownloadUrl(projectId: string): string {
  return `${API_BASE}/projects/${projectId}/export/download`
}

export function normalizeScoredSegments(
  scored: SegmentsResponse['scored'],
): import('./types').ScoredSegment[] {
  if (Array.isArray(scored)) return scored
  return scored.segments ?? []
}
