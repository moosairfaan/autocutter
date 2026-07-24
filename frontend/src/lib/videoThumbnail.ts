/**
 * Grab a still frame from a local video File via a hidden <video> + <canvas>.
 * Returns a JPEG data URL, or rejects on failure (caller should show a placeholder).
 */
export function generateVideoThumbnail(file: File): Promise<string> {
  return new Promise((resolve, reject) => {
    const objectUrl = URL.createObjectURL(file)
    const video = document.createElement('video')
    video.preload = 'auto'
    video.muted = true
    video.playsInline = true
    video.setAttribute('playsinline', 'true')

    let settled = false
    const settle = (fn: () => void) => {
      if (settled) return
      settled = true
      window.clearTimeout(timer)
      try {
        URL.revokeObjectURL(objectUrl)
      } catch {
        /* ignore */
      }
      video.removeAttribute('src')
      video.load()
      fn()
    }

    const fail = (reason: string) => {
      settle(() => reject(new Error(reason)))
    }

    const timer = window.setTimeout(() => fail('thumbnail timeout'), 8000)

    video.addEventListener('error', () => fail('video load error'))

    const capture = () => {
      try {
        const w = video.videoWidth
        const h = video.videoHeight
        if (!w || !h) {
          fail('no video dimensions')
          return
        }
        const maxW = 640
        const scale = Math.min(1, maxW / w)
        const canvas = document.createElement('canvas')
        canvas.width = Math.max(1, Math.round(w * scale))
        canvas.height = Math.max(1, Math.round(h * scale))
        const ctx = canvas.getContext('2d')
        if (!ctx) {
          fail('no canvas context')
          return
        }
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height)
        const dataUrl = canvas.toDataURL('image/jpeg', 0.82)
        settle(() => resolve(dataUrl))
      } catch (err) {
        fail(err instanceof Error ? err.message : 'capture failed')
      }
    }

    video.addEventListener('seeked', capture, { once: true })

    video.addEventListener(
      'loadedmetadata',
      () => {
        const duration = video.duration
        let seekTo = 1
        if (Number.isFinite(duration) && duration > 0) {
          seekTo = Math.min(Math.max(0.1, duration * 0.1), Math.max(0.05, duration - 0.05))
        }
        try {
          video.currentTime = seekTo
        } catch {
          // Some formats reject seek before loadeddata — try capture at 0.
          capture()
        }
      },
      { once: true },
    )

    video.src = objectUrl
  })
}
