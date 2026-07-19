/** Format seconds as H:MM:SS.ff or M:SS.ff */
export function formatTimecode(seconds: number, withFrames = false): string {
  if (!Number.isFinite(seconds) || seconds < 0) seconds = 0
  const h = Math.floor(seconds / 3600)
  const m = Math.floor((seconds % 3600) / 60)
  const s = Math.floor(seconds % 60)
  const frac = Math.floor((seconds % 1) * 100)
  const mm = String(m).padStart(2, '0')
  const ss = String(s).padStart(2, '0')
  const ff = String(frac).padStart(2, '0')
  const core = h > 0 ? `${h}:${mm}:${ss}` : `${m}:${ss}`
  return withFrames ? `${core}.${ff}` : core
}
