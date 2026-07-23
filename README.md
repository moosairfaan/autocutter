# Autocutter

Turn long-form video/podcast footage into a rough cut automatically, using AI to find the best/most relevant parts based on your target length and optional theme.

## Two ways to use this

**1. CLI tool → Final Cut Pro X**
The original version. Outputs an `.fcpxml` file + a readable edit report — you import the XML into Final Cut Pro X to review/finish the edit yourself. No rendered video, no cloud, just decisions handed to FCP.

**2. Web app → downloadable MP4**
The newer version. A local web app (FastAPI backend + React frontend) where you upload a video, review the AI's suggested cuts in a browser UI (approve/reject each segment), and export a finished, already-cut MP4 directly — no Final Cut Pro required at all. Runs entirely on your machine.

## Why local-only?

This runs entirely on your machine — no hosted version, no cloud deployment planned for now. Reasons:
- Whisper transcription and video export are compute/time-heavy (minutes, not seconds) — not a fit for typical serverless hosting
- Large video files (podcasts/vlogs can be several GB) don't play well with most hosting upload limits
- You bring your own Anthropic API key and pay for your own usage — no shared key, no surprise bills
- Your video never leaves your machine

If you want to use this, clone it and run it locally (instructions below). A packaged desktop app (no terminal required) may come later, but there's no plan for a hosted web version.

## Status

- CLI + FCPXML export: working
- Web app: working — upload, transcribe, AI scoring, timeline keep/cut, drag-to-reorder, trim handles, export finished MP4

## Requirements

Shared (both tools):

- macOS
- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) on your `PATH` (`brew install ffmpeg`)
- An [Anthropic API key](https://console.anthropic.com/)

CLI only:

- Final Cut Pro X (to import the `.fcpxml`)

Web app only:

- Node.js 18+ (for the React/Vite frontend)

## Install (shared base)

```bash
git clone <repo-url>
cd autocutter
python3 -m venv venv && source venv/bin/activate
pip install -e .
cp .env.example .env   # then add your ANTHROPIC_API_KEY
```

Or paste the key on first CLI run / save it to `~/.autocutter/.env`.

### CLI-only extras

Nothing else — `pip install -e .` is enough for the `autocutter` command.

### Web app extras

```bash
source venv/bin/activate
pip install -e '.[api]'
cd frontend && npm install && cd ..
```

## Quick start — CLI → Final Cut Pro X

```bash
source venv/bin/activate

# Interactive prompts
autocutter

# Or flags
autocutter --video path/to/footage.mp4 --target-minutes 30 \
  --focus "life on Long Island as new grads"
```

Useful extras: `--skip-to select` to re-cut from cached scores, `--force` to ignore caches, `--model small` / `--no-word-timestamps` for a faster Whisper run (or set `WHISPER_MODEL` / `WHISPER_WORD_TIMESTAMPS` in `.env`).

### Fast Whisper (demo)

Defaults stay `medium` + word timestamps. For a quicker pass, put this in `./.env` or `~/.autocutter/.env` (restart the API after changing):

```bash
WHISPER_MODEL=small
WHISPER_WORD_TIMESTAMPS=false
```

Or on the CLI: `autocutter --model small --no-word-timestamps ...`. At start of transcription the process logs `Whisper config: model=... word_timestamps=...`.

### What the CLI gives you

It does **not** render an edited video. It writes under `./output/<video-slug>/`:

- `autocut.fcpxml` — import via **File → Import → XML** in Final Cut Pro X
- `edit_report.md` — keep/cut decisions for a quick sanity check
- Cached intermediates: `audio.wav`, `transcript.json`, `scored_segments.json`

## Quick start — Web app → MP4

Two terminals, from the repo root:

```bash
# Terminal 1 — API
source venv/bin/activate
uvicorn backend.main:app --reload --port 8000

# Terminal 2 — UI
cd frontend && npm run dev
```

Open http://localhost:5173 (Vite proxies `/api` → `:8000`).

Flow: upload video → set target length / focus → process (Whisper + Claude) → approve/reject segments in the browser → **Save & Export** → download the MP4.

Projects and Whisper models live under `~/.autocutter/` (`projects/`, `models/`, optional `.env`).

## How it works

Same core pipeline for both tools:

1. **Extract audio** with ffmpeg
2. **Transcribe** with faster-whisper (word-level timestamps → sentence/pause segments)
3. **Score segments** with Claude (interest + optional theme)
4. **Select** a keep set for your target length
5. **Output**
   - CLI: FCPXML + edit report
   - Web: keep/cut UI → ffmpeg trim+concat → downloadable H.264/AAC MP4 (optional audio cleanup)

## Cost

Anthropic usage scales with footage length. Scoring runs in ~12-minute chunks, so expect roughly **~5 API calls per hour** of video (plus a bit of overlap). Transcription and export are local and don't hit Anthropic.

## License

MIT
