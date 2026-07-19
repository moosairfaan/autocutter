import { useCallback, useState, type DragEvent, type ChangeEvent } from 'react'

type Props = {
  file: File | null
  disabled?: boolean
  onFile: (file: File | null) => void
}

const ACCEPT = 'video/mp4,video/quicktime,video/x-m4v,video/webm,video/x-matroska,.mp4,.mov,.m4v,.webm,.mkv'

export function FileDrop({ file, disabled, onFile }: Props) {
  const [over, setOver] = useState(false)

  const pick = useCallback(
    (next: File | null) => {
      if (!next) {
        onFile(null)
        return
      }
      if (!next.type.startsWith('video/') && !/\.(mp4|mov|m4v|webm|mkv|avi)$/i.test(next.name)) {
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
        'relative flex min-h-56 cursor-pointer flex-col items-center justify-center rounded-2xl border-2 border-dashed px-6 py-10 text-center transition',
        over ? 'border-accent bg-accent/10' : 'border-ink/20 bg-white/60 hover:border-ink/40',
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
      <p className="font-display text-xl font-bold tracking-tight text-ink">
        {file ? file.name : 'Drop your video here'}
      </p>
      <p className="mt-2 max-w-sm text-sm text-slate">
        {file
          ? `${(file.size / (1024 * 1024)).toFixed(1)} MB — click to replace`
          : 'or click to browse · mp4, mov, webm'}
      </p>
    </label>
  )
}
