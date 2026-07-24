import type { ProcessOptions, ProgressEvent, SegmentsResponse } from './types'

const API_BASE = '/api'

type ParsedSse = {
  sseEvent: string
  data: ProgressEvent
}

function parseSseChunk(chunk: string): ParsedSse | null {
  let sseEvent = 'message'
  const dataLines: string[] = []

  for (const rawLine of chunk.split('\n')) {
    const line = rawLine.replace(/\r$/, '')
    // SSE comments / keepalives (e.g. ": ping") — ignore, never parse as data.
    if (line.startsWith(':') || line.trim() === '') continue
    if (line.startsWith('event:')) {
      sseEvent = line.slice(6).trim()
    } else if (line.startsWith('data:')) {
      dataLines.push(line.slice(5).trimStart())
    }
    // Ignore unknown fields (id:, retry:, etc.)
  }

  // No data lines → comment-only keepalive or empty block (not an error).
  if (!dataLines.length) return null
  const data = JSON.parse(dataLines.join('\n')) as ProgressEvent
  return { sseEvent, data }
}

function isTerminalComplete(parsed: ParsedSse): boolean {
  const { sseEvent, data } = parsed
  return (
    sseEvent === 'complete' ||
    sseEvent === 'done' ||
    data.event === 'complete' ||
    data.event === 'done' ||
    data.status === 'done'
  )
}

function isTerminalError(parsed: ParsedSse): boolean {
  const { sseEvent, data } = parsed
  return (
    sseEvent === 'error' ||
    data.event === 'error' ||
    data.status === 'error'
  )
}

function handleParsed(
  parsed: ParsedSse,
  onProgress: (event: ProgressEvent) => void,
): 'complete' | 'error' | 'continue' {
  const evt: ProgressEvent = {
    ...parsed.data,
    // Normalize so UI always sees a familiar event name.
    event: isTerminalComplete(parsed)
      ? 'complete'
      : isTerminalError(parsed)
        ? 'error'
        : (parsed.data.event ?? 'progress'),
    progress: parsed.data.progress ?? (isTerminalComplete(parsed) ? 1 : 0),
    step: parsed.data.step ?? parsed.sseEvent,
  }

  console.log('[SSE]', parsed.sseEvent, evt)
  onProgress(evt)

  if (isTerminalError(parsed)) return 'error'
  if (isTerminalComplete(parsed)) return 'complete'
  return 'continue'
}

export async function createProject(
  file: File,
): Promise<{ project_id: string; bytes_written?: number }> {
  if (!(file instanceof File) || file.size <= 0) {
    throw new Error(`Invalid upload File object (size=${(file as File)?.size ?? 'n/a'})`)
  }
  console.log('[upload] appending File to FormData', {
    name: file.name,
    size: file.size,
    type: file.type,
    field: 'video',
  })

  const form = new FormData()
  // Field name MUST match FastAPI param: video: UploadFile = File(...)
  form.append('video', file, file.name)

  const res = await fetch(`${API_BASE}/projects`, {
    method: 'POST',
    // Do NOT set Content-Type manually — browser sets multipart boundary.
    body: form,
  })
  if (!res.ok) {
    const detail = await res.text()
    throw new Error(detail || `Upload failed (${res.status})`)
  }
  const json = (await res.json()) as {
    project_id: string
    bytes_written?: number
  }
  console.log('[upload] server response', json)
  if (
    typeof json.bytes_written === 'number' &&
    json.bytes_written !== file.size
  ) {
    throw new Error(
      `Upload size mismatch: browser file is ${file.size} bytes but server wrote ${json.bytes_written}`,
    )
  }
  return json
}

/**
 * Read an SSE stream until event:complete or event:error.
 * No client-side time limit — waits as long as the server keeps the connection
 * open (analyze/LLM steps can idle for minutes with only ": ping" keepalives).
 *
 * Important: sse-starlette emits CRLF (\\r\\n). Event boundaries are \\r\\n\\r\\n,
 * so we normalize to \\n before splitting — splitting on "\\n\\n" alone never
 * matches and the whole stream piles up until close, then JSON.parse fails.
 */
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
  let lastComplete: ProgressEvent | null = null

  const consumeParts = (parts: string[]): ProgressEvent | null => {
    for (const part of parts) {
      if (!part.trim()) continue
      // Comment-only keepalive blocks (": ping") — skip without warning.
      const nonComment = part
        .split('\n')
        .map((l) => l.replace(/\r$/, ''))
        .filter((l) => l.trim() !== '' && !l.startsWith(':'))
      if (nonComment.length === 0) {
        continue
      }

      let parsed: ParsedSse | null
      try {
        parsed = parseSseChunk(part)
      } catch (err) {
        console.warn('[SSE] failed to parse chunk', part, err)
        continue
      }
      if (!parsed) continue
      const result = handleParsed(parsed, onProgress)
      if (result === 'error') {
        throw new Error(parsed.data.message || emptyMessage)
      }
      if (result === 'complete') {
        lastComplete = {
          ...parsed.data,
          event: 'complete',
          status: 'done',
          progress: parsed.data.progress ?? 1,
        }
        return lastComplete
      }
    }
    return null
  }

  // Loop until the server closes the stream or we see a terminal event.
  // Intentionally no setTimeout / AbortSignal timeout here.
  while (true) {
    const { done, value } = await reader.read()
    if (done) {
      buffer += decoder.decode().replace(/\r\n/g, '\n').replace(/\r/g, '\n')
      if (buffer.trim()) {
        const finished = consumeParts(buffer.split('\n\n'))
        if (finished) return finished
      }
      break
    }
    buffer += decoder.decode(value, { stream: true })
    // Normalize CRLF from sse-starlette so "\n\n" event delimiters work.
    buffer = buffer.replace(/\r\n/g, '\n').replace(/\r/g, '\n')
    const parts = buffer.split('\n\n')
    buffer = parts.pop() ?? ''
    const finished = consumeParts(parts)
    if (finished) return finished
  }

  if (lastComplete) return lastComplete
  console.error('[SSE]', emptyMessage, { buffer })
  throw new Error(emptyMessage)
}

export async function processProject(
  projectId: string,
  options: ProcessOptions,
  onProgress: (event: ProgressEvent) => void,
  signal?: AbortSignal,
): Promise<ProgressEvent> {
  // No timeout on this fetch — only abort if the caller passes an explicit signal
  // (e.g. user cancelled). Do not wrap with AbortSignal.timeout(...).
  const res = await fetch(`${API_BASE}/projects/${projectId}/process`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Accept: 'text/event-stream',
    },
    body: JSON.stringify({
      focus: options.focus || null,
      target_minutes: options.target_minutes ?? null,
      // Omit model so the backend can use WHISPER_MODEL env (default medium).
      ...(options.model != null ? { model: options.model } : {}),
      ...(options.word_timestamps != null
        ? { word_timestamps: options.word_timestamps }
        : {}),
      force: options.force ?? false,
    }),
    signal, // optional; never auto-timeout
  })

  return readSseProgress(res, onProgress, 'Processing ended without a completion event')
}

export async function exportProject(
  projectId: string,
  onProgress: (event: ProgressEvent) => void,
  options: {
    clean_audio?: boolean
    resolution?: 'original' | '1080p' | '720p'
  } = {},
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
      resolution: options.resolution ?? 'original',
    }),
    signal, // optional; never auto-timeout
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
  segments: import('./types').ApiEditSegment[],
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
