# autocutter

Turn long-form video/podcast footage into a Final Cut Pro X rough cut using AI, based on your target length and optional theme.

## Requirements

- macOS
- Python 3.11+
- [ffmpeg](https://ffmpeg.org/) (`brew install ffmpeg`)
- Final Cut Pro X
- An [Anthropic API key](https://console.anthropic.com/)

## Install

```bash
git clone <repo-url>
cd autocutter
python3 -m venv venv && source venv/bin/activate
pip install -e .
```

On first run, autocutter checks for ffmpeg and an API key. You can paste a key interactively and save it to `~/.autocutter/.env`, or put `ANTHROPIC_API_KEY=...` in a local `.env`.

## Quick start

Interactive (guided prompts):

```bash
autocutter
```

Flags:

```bash
autocutter --video path/to/footage.mp4 --target-minutes 30 \
  --focus "life on Long Island as new grads"
```

Useful extras: `--skip-to select` to re-cut from cached scores, `--force` to ignore caches, `--model small` for a faster Whisper model.

## What you get

autocutter does **not** export an edited video. It writes:

- `autocut.fcpxml` — import via **File → Import → XML** in Final Cut Pro X
- `edit_report.md` — keep/cut decisions for a quick sanity check

Plus cached intermediates (`audio.wav`, `transcript.json`, `scored_segments.json`) under `./output/<video-slug>/` (override the base with `--output-dir`).

## How it works

1. **Extract audio** from the video with ffmpeg
2. **Transcribe** with faster-whisper
3. **Score segments** with Claude (interest + optional theme)
4. **Select** a keep set that hits your target length
5. **Generate FCPXML** (+ edit report) for FCPX

Whisper models cache under `~/.autocutter/models`.

## Cost

Anthropic usage scales with footage length. Scoring runs in ~12-minute chunks, so expect roughly **~5 API calls per hour** of video (plus a bit of overlap). Transcription is local via Whisper and doesn't hit Anthropic.

## License

MIT
