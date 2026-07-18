"""Extract audio from a video file for transcription."""

from __future__ import annotations

import subprocess
from pathlib import Path


def extract_audio(video_path: Path, output_dir: Path) -> Path:
    """Extract mono 16 kHz WAV audio from *video_path* into *output_dir*/audio.wav."""
    video_path = Path(video_path)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "audio.wav"

    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video_path),
        "-vn",
        "-acodec",
        "pcm_s16le",
        "-ac",
        "1",
        "-ar",
        "16000",
        str(output_path),
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg not found. Install it with: brew install ffmpeg"
        ) from exc

    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed while extracting audio from {video_path} "
            f"(exit code {result.returncode}):\n{result.stderr.strip()}"
        )

    return output_path
