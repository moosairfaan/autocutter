"""Transcribe audio with faster-whisper."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from faster_whisper import WhisperModel

from autocutter import AUTOCUTTER_MODELS


def transcribe(
    audio_path: Path,
    model_size: str = "medium",
    output_dir: Path | None = None,
) -> list[dict[str, Any]]:
    """Transcribe *audio_path* and save segments to *output_dir*/transcript.json.

    Uses faster-whisper's built-in segmentation (no merge/split). Runs on CPU
    with int8 by default so no GPU is required. Models cache under
    ~/.autocutter/models.
    """
    audio_path = Path(audio_path)
    if output_dir is None:
        output_dir = audio_path.parent
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    AUTOCUTTER_MODELS.mkdir(parents=True, exist_ok=True)

    print(f"Loading Whisper model '{model_size}' (CPU, int8)...")
    try:
        model = WhisperModel(
            model_size,
            device="cpu",
            compute_type="int8",
            download_root=str(AUTOCUTTER_MODELS),
        )
    except Exception as exc:
        # Graceful fallback if int8/CPU path fails for any reason.
        print(f"CPU/int8 load failed ({exc}); retrying with device=auto")
        model = WhisperModel(
            model_size,
            device="auto",
            compute_type="default",
            download_root=str(AUTOCUTTER_MODELS),
        )
    print(f"Transcribing {audio_path}...")
    segments_iter, _info = model.transcribe(str(audio_path))

    segments: list[dict[str, Any]] = []
    for i, segment in enumerate(segments_iter):
        segments.append(
            {
                "id": i,
                "start": segment.start,
                "end": segment.end,
                "text": segment.text.strip(),
            }
        )
        if (i + 1) % 20 == 0:
            print(f"  transcribed {i + 1} segments... (last end={segment.end:.1f}s)")

    transcript_path = output_dir / "transcript.json"
    with transcript_path.open("w", encoding="utf-8") as f:
        json.dump(segments, f, indent=2, ensure_ascii=False)

    print(f"Transcription complete: {len(segments)} segments → {transcript_path}")
    return segments
