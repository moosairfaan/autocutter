# Autocutter

Turn long-form video/podcast footage into a rough cut automatically, using AI to find the best/most relevant parts based on your target length and optional theme.

## Two ways to use this

**1. CLI tool → Final Cut Pro X**  
Outputs an `.fcpxml` file + a readable edit report — import into Final Cut Pro X to finish the edit. No rendered video, no cloud.

**2. Web app → downloadable MP4**  
Local FastAPI + React app: upload a video, review AI cuts on a timeline (keep/cut, drag-to-reorder, trim handles), export a finished H.264/AAC MP4. No Final Cut Pro required.

## Why local-only?

- Whisper transcription and video export are compute-heavy (minutes, not seconds)
- Large source files don’t fit typical hosted upload limits
- You bring your own Anthropic API key — no shared billing
- Footage never leaves your machine

## Status

- CLI + FCPXML export: working
- Web app: working — upload, Whisper, Claude scoring, timeline keep/cut, drag-to-reorder, trim handles, Save & Export MP4
- Config: Whisper model / word-timestamps via `.env` or CLI flags
- Tests: pytest suite for scoring (mocked Anthropic) and FCPXML generation (mocked ffprobe)

## Requirements

**Shared**

- macOS
- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) on `PATH` (`brew install ffmpeg`)
- [Anthropic API key](https://console.anthropic.com/)

**CLI only:** Final Cut Pro X (to import `.fcpxml`)

**Web only:** Node.js 18+

## Install

```bash
git clone <repo-url>
cd autocutter
python3 -m venv venv && source venv/bin/activate
pip install -e .
cp .env.example .env   # set ANTHROPIC_API_KEY
```

Or paste the key on first CLI run / save it to `~/.autocutter/.env`.

### Web app extras

```bash
source venv/bin/activate
pip install -e '.[api]'
cd frontend && npm install && cd ..
```

### Dev / tests

```bash
source venv/bin/activate
pip install -e '.[dev]'
pytest
```

## Configuration (`.env`)

Copy `.env.example` → `./.env` or `~/.autocutter/.env`:

| Variable | Default | Purpose |
|---|---|---|
| `ANTHROPIC_API_KEY` | *(required)* | Claude scoring |
| `WHISPER_MODEL` | `medium` | faster-whisper size (`tiny` / `base` / `small` / `medium` / `large`) |
| `WHISPER_WORD_TIMESTAMPS` | `true` | Word-level timestamps (`false` is faster for demos) |
| `TRIM_FILLER_WORDS` | `false` | At export, micro-cut `um`/`uh` (and cautious `like`/`so`/`right`) inside kept segments — needs `words.json` |

Restart the API after changing env vars. Delete or force-refresh `transcript.json` if you already transcribed with different settings.

**Fast demo:**

```bash
WHISPER_MODEL=small
WHISPER_WORD_TIMESTAMPS=false
```

## Quick start — CLI → Final Cut Pro X

```bash
source venv/bin/activate

# Interactive
autocutter

# Flags
autocutter --video path/to/footage.mp4 --target-minutes 30 \
  --focus "life on Long Island as new grads"

# Faster Whisper
autocutter --video path/to/footage.mp4 --model small --no-word-timestamps
```

Useful flags: `--skip-to select` (re-cut from cached scores), `--force` (ignore caches), `--model`, `--word-timestamps` / `--no-word-timestamps`.

### CLI output (`./output/<video-slug>/`)

- `autocut.fcpxml` — **File → Import → XML** in Final Cut Pro X
- `edit_report.md` — keep/cut sanity check
- Caches: `audio.wav`, `transcript.json`, `scored_segments.json`

## Quick start — Web app → MP4

```bash
# Terminal 1 — API
source venv/bin/activate
uvicorn backend.main:app --reload --port 8000

# Terminal 2 — UI
cd frontend && npm run dev
```

Open http://localhost:5173 (Vite proxies `/api` → `:8000`).

**Flow**

1. Upload video → set target length / optional focus
2. Process (ffmpeg → Whisper → Claude → select) with live SSE progress
3. Edit on the timeline: keep/cut, drag blocks to reorder, drag edges to trim
4. **Save & Export** → optional audio cleanup → download MP4

Projects and Whisper models live under `~/.autocutter/` (`projects/`, `models/`, optional `.env`).

### Web editor details

- Kept blocks are ordered by `order` (not source chronology); width ∝ trim length
- Cut segments sit in a collapsed list; restoring one appends to the end of the timeline
- Export uses each segment’s `trim_in` / `trim_out` and concat order from `order`
- Invalid trims or gapped/duplicate orders return a clear HTTP 400 before ffmpeg runs

## How it works

1. **Extract audio** — ffmpeg → `audio.wav`
2. **Transcribe** — faster-whisper → word/segment timestamps → sentence/pause segments (`transcript.json`)
3. **Score** — Claude scores ~12‑minute chunks (`score`, `tag`, `on_theme`) → `scored_segments.json`
4. **Select** — greedy cut-worst-first to hit target length (theme as tie-break) → `edit_decision.json`
5. **Output**
   - CLI: FCPXML + edit report
   - Web: timeline edits → PATCH segments → ffmpeg `trim` + `concat` → `export.mp4`

Progress for long jobs streams over **SSE** (in-process worker thread; no external job queue yet).

## Project layout

```
autocutter/          # Shared library + CLI (transcribe, analyze, select, FCPXML)
backend/             # FastAPI (upload, process SSE, segments, export)
frontend/            # React + Vite timeline editor
tests/               # pytest (mocked Anthropic + FCPXML)
```

## Cost

Anthropic usage scales with footage length. Scoring uses ~12‑minute chunks → roughly **~5 API calls per hour** of video (plus overlap). Transcription and export are local.

## License

MIT
