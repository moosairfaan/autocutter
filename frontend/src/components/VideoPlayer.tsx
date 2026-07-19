import { forwardRef, useEffect, useImperativeHandle, useRef, useState } from 'react'
import { formatTimecode } from '../lib/time'

export type VideoPlayerHandle = {
  seek: (time: number) => void
}

type Props = {
  src: string
}

export const VideoPlayer = forwardRef<VideoPlayerHandle, Props>(function VideoPlayer(
  { src },
  ref,
) {
  const videoRef = useRef<HTMLVideoElement>(null)
  const [playing, setPlaying] = useState(false)
  const [current, setCurrent] = useState(0)
  const [duration, setDuration] = useState(0)

  useImperativeHandle(ref, () => ({
    seek(time: number) {
      const el = videoRef.current
      if (!el) return
      const next = Math.max(0, time)
      el.currentTime = next
      setCurrent(next)
    },
  }))

  useEffect(() => {
    setPlaying(false)
    setCurrent(0)
    setDuration(0)
  }, [src])

  const toggle = () => {
    const el = videoRef.current
    if (!el) return
    if (el.paused) {
      void el.play()
    } else {
      el.pause()
    }
  }

  const onScrub = (value: number) => {
    const el = videoRef.current
    if (!el) return
    el.currentTime = value
    setCurrent(value)
  }

  return (
    <div className="flex w-full flex-col gap-3">
      <div className="relative overflow-hidden rounded-xl bg-black shadow-lg ring-1 ring-black/40">
        <video
          ref={videoRef}
          src={src}
          className="aspect-video w-full bg-black object-contain"
          playsInline
          preload="metadata"
          onClick={toggle}
          onPlay={() => setPlaying(true)}
          onPause={() => setPlaying(false)}
          onTimeUpdate={() => setCurrent(videoRef.current?.currentTime ?? 0)}
          onLoadedMetadata={() => setDuration(videoRef.current?.duration ?? 0)}
          onDurationChange={() => setDuration(videoRef.current?.duration ?? 0)}
        />
      </div>

      <div className="flex flex-col gap-2 rounded-xl bg-panel px-4 py-3 text-paper">
        <input
          type="range"
          min={0}
          max={duration || 0}
          step={0.01}
          value={Math.min(current, duration || 0)}
          disabled={!duration}
          onChange={(e) => onScrub(Number(e.target.value))}
          className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-panel-2 accent-accent disabled:opacity-40"
          aria-label="Scrub"
        />
        <div className="flex items-center justify-between gap-4">
          <button
            type="button"
            onClick={toggle}
            className="rounded-lg bg-accent px-4 py-1.5 font-display text-sm font-bold tracking-wide text-white transition hover:bg-accent-dim"
          >
            {playing ? 'Pause' : 'Play'}
          </button>
          <div className="font-mono text-sm tracking-wider text-mist">
            <span className="text-white">{formatTimecode(current, true)}</span>
            <span className="mx-2 text-slate">/</span>
            <span>{formatTimecode(duration, true)}</span>
          </div>
        </div>
      </div>
    </div>
  )
})
