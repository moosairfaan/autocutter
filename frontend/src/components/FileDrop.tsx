import {
  useCallback,
  useEffect,
  useState,
  type DragEvent,
  type ChangeEvent,
} from 'react'
import { generateVideoThumbnail } from '../lib/videoThumbnail'

type Props = {
  file: File | null
  disabled?: boolean
  onFile: (file: File | null) => void
}

const ACCEPT =
  'video/mp4,video/quicktime,video/x-m4v,video/webm,video/x-matroska,.mp4,.mov,.m4v,.webm,.mkv'

function VideoPlaceholder() {
  return (
    <div
      className="flex h-full w-full items-center justify-center bg-mist/80"
      aria-hidden
    >
      <svg
        viewBox="0 0 64 64"
        className="h-16 w-16 text-accent"
        fill="none"
        stroke="currentColor"
        strokeWidth="2"
      >
        <rect x="8" y="14" width="48" height="36" rx="6" />
        <path d="M28 24v16l14-8-14-8z" fill="currentColor" stroke="none" />
      </svg>
    </div>
  )
}

function DropIcon() {
  return (
    <div
      className="mb-4 flex h-14 w-14 items-center justify-center rounded-2xl bg-accent/15 text-accent ring-1 ring-accent/30"
      aria-hidden
    >
      <svg viewBox="0 0 24 24" className="h-7 w-7" fill="none" stroke="currentColor" strokeWidth="1.75">
        <path d="M12 16V4m0 0 4 4m-4-4-4 4" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M4 14v4a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2v-4" strokeLinecap="round" />
      </svg>
    </div>
  )
}

export function FileDrop({ file, disabled, onFile }: Props) {
  const [over, setOver] = useState(false)
  const [thumbUrl, setThumbUrl] = useState<string | null>(null)
  const [thumbFailed, setThumbFailed] = useState(false)

  useEffect(() => {
    if (!file) {
      setThumbUrl(null)
      setThumbFailed(false)
      return
    }

    let cancelled = false
    setThumbUrl(null)
    setThumbFailed(false)

    void generateVideoThumbnail(file)
      .then((url) => {
        if (!cancelled) {
          setThumbUrl(url)
          setThumbFailed(false)
        }
      })
      .catch(() => {
        if (!cancelled) {
          setThumbUrl(null)
          setThumbFailed(true)
        }
      })

    return () => {
      cancelled = true
    }
  }, [file])

  const pick = useCallback(
    (next: File | null) => {
      if (!next) {
        onFile(null)
        return
      }
      if (
        !next.type.startsWith('video/') &&
        !/\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(next.name)
      ) {
        return
      }
      onFile(next)
    },
    [onFile],
  )

  const onDrop = (e: DragEvent) => {
    e.preventDefault()
    setOver(false)
    if (disabled) return
    const f = e.dataTransfer.files?.[0]
    if (f) pick(f)
  }

  const onChange = (e: ChangeEvent<HTMLInputElement>) => {
    const f = e.target.files?.[0] ?? null
    pick(f)
  }

  return (
    <label
      onDragEnter={(e) => {
        e.preventDefault()
        if (!disabled) setOver(true)
      }}
      onDragOver={(e) => {
        e.preventDefault()
        if (!disabled) setOver(true)
      }}
      onDragLeave={() => setOver(false)}
      onDrop={onDrop}
      className={[
        'relative flex min-h-72 cursor-pointer flex-col items-center justify-center overflow-hidden rounded-2xl border-2 border-dashed text-center transition duration-200',
        over
          ? 'border-accent bg-accent/10 shadow-lg shadow-accent/20'
          : 'border-white/15 bg-panel hover:border-accent/50 hover:bg-panel/80',
        disabled ? 'pointer-events-none opacity-60' : '',
      ].join(' ')}
    >
      <input
        type="file"
        accept={ACCEPT}
        className="sr-only"
        disabled={disabled}
        onChange={onChange}
      />

      {file ? (
        <div className="absolute inset-0">
          {thumbUrl ? (
            <img
              src={thumbUrl}
              alt=""
              className="h-full w-full object-cover"
            />
          ) : (
            <VideoPlaceholder />
          )}
          <div className="absolute inset-0 bg-gradient-to-t from-panel via-panel/40 to-transparent" />
          <div className="absolute inset-x-0 bottom-0 px-5 py-5 text-left">
            <p className="truncate font-display text-lg font-bold tracking-tight text-paper">
              {file.name}
            </p>
            <p className="mt-1 text-sm text-slate">
              {(file.size / (1024 * 1024)).toFixed(1)} MB
              {thumbFailed
                ? ' · preview unavailable — click to replace'
                : thumbUrl
                  ? ' — click to replace'
                  : ' · loading preview…'}
            </p>
          </div>
        </div>
      ) : (
        <div className="flex flex-col items-center px-8 py-12">
          <DropIcon />
          <p className="font-display text-xl font-bold tracking-tight text-ink">
            Drop your video here
          </p>
          <p className="mt-2 max-w-sm text-sm leading-relaxed text-slate">
            or click to browse · mp4, mov, webm
          </p>
        </div>
      )}
    </label>
  )
}
