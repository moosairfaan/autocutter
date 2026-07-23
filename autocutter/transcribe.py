"""Transcribe audio with faster-whisper."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv
from faster_whisper import WhisperModel

from autocutter import AUTOCUTTER_ENV, AUTOCUTTER_MODELS

# Split when the gap between consecutive words exceeds this (seconds).
PAUSE_THRESHOLD_S = 0.6

DEFAULT_WHISPER_MODEL = "medium"
DEFAULT_WORD_TIMESTAMPS = True


def _load_whisper_env() -> None:
    """Load .env files the same way as the API key (home then cwd)."""
    load_dotenv(AUTOCUTTER_ENV)
    load_dotenv()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or not str(raw).strip():
        return default
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def resolve_whisper_model(explicit: str | None = None) -> str:
    """CLI/API override → WHISPER_MODEL env → medium."""
    if isinstance(explicit, str) and explicit.strip():
        return explicit.strip()
    _load_whisper_env()
    env = (os.environ.get("WHISPER_MODEL") or "").strip()
    return env or DEFAULT_WHISPER_MODEL


def resolve_word_timestamps(explicit: bool | None = None) -> bool:
    """CLI/API override → WHISPER_WORD_TIMESTAMPS env → True."""
    if explicit is not None:
        return bool(explicit)
    _load_whisper_env()
    return _env_bool("WHISPER_WORD_TIMESTAMPS", DEFAULT_WORD_TIMESTAMPS)

# Sentence-ending punctuation, optionally followed by closing quotes/brackets.
_SENTENCE_END_RE = re.compile(r'[.?!]["\')\]]*$')


def _ends_sentence(word: str) -> bool:
    return bool(_SENTENCE_END_RE.search(word.strip()))


def _finalize_segment(seg_id: int, words: list[dict[str, Any]]) -> dict[str, Any]:
    # faster-whisper word strings usually already include a leading space.
    text = "".join(w["word"] for w in words).strip()
    return {
        "id": seg_id,
        "start": float(words[0]["start"]),
        "end": float(words[-1]["end"]),
        "text": text,
    }


def segments_to_natural_boundaries(
    word_level_data: list[dict[str, Any]],
    *,
    pause_threshold_s: float = PAUSE_THRESHOLD_S,
) -> list[dict[str, Any]]:
    """Regroup word-level timestamps into sentence/pause-bounded segments.

    Splits after a word that ends with ``.``, ``?``, or ``!``, or when the
    gap between consecutive words is greater than *pause_threshold_s*.
    Every returned segment therefore starts/ends on a clean break rather than
    mid-word (Whisper's default chunking).

    *word_level_data* items should look like
    ``{"word": " Hello.", "start": 1.2, "end": 1.6}`` (``text`` is also
    accepted as an alias for ``word``).
    """
    words: list[dict[str, Any]] = []
    for item in word_level_data:
        raw = item.get("word", item.get("text", ""))
        text = str(raw).strip() if raw is not None else ""
        if not text:
            continue
        # Preserve original token (often has a leading space) for joining.
        token = str(raw)
        words.append(
            {
                "word": token,
                "start": float(item["start"]),
                "end": float(item["end"]),
            }
        )

    if not words:
        return []

    segments: list[dict[str, Any]] = []
    current: list[dict[str, Any]] = [words[0]]

    for i in range(1, len(words)):
        prev = words[i - 1]
        curr = words[i]
        gap = float(curr["start"]) - float(prev["end"])
        split = _ends_sentence(prev["word"]) or gap > pause_threshold_s
        if split:
            segments.append(_finalize_segment(len(segments), current))
            current = [curr]
        else:
            current.append(curr)

    if current:
        segments.append(_finalize_segment(len(segments), current))

    return segments


def transcribe(
    audio_path: Path,
    model_size: str | None = None,
    output_dir: Path | None = None,
    *,
    word_timestamps: bool | None = None,
) -> list[dict[str, Any]]:
    """Transcribe *audio_path* and save segments to *output_dir*/transcript.json.

    Uses faster-whisper, then regroups on sentence endings / long pauses so cut
    points land on clean boundaries. Runs on CPU with int8 by default. Models
    cache under ~/.autocutter/models.

    ``model_size`` / ``word_timestamps`` default from env (``WHISPER_MODEL``,
    ``WHISPER_WORD_TIMESTAMPS``) then to medium / True when unset.
    """
    audio_path = Path(audio_path)
    if output_dir is None:
        output_dir = audio_path.parent
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    AUTOCUTTER_MODELS.mkdir(parents=True, exist_ok=True)

    model_size = resolve_whisper_model(model_size)
    use_word_ts = resolve_word_timestamps(word_timestamps)
    print(
        f"Whisper config: model={model_size!r} "
        f"word_timestamps={use_word_ts} (device=cpu, compute_type=int8)"
    )

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

    ts_label = "word timestamps" if use_word_ts else "segment timestamps"
    print(f"Transcribing {audio_path} ({ts_label})...")
    segments_iter, _info = model.transcribe(
        str(audio_path),
        word_timestamps=use_word_ts,
    )

    word_level: list[dict[str, Any]] = []
    whisper_seg_count = 0
    for segment in segments_iter:
        whisper_seg_count += 1
        if use_word_ts and segment.words:
            for word in segment.words:
                word_level.append(
                    {
                        "word": word.word,
                        "start": word.start,
                        "end": word.end,
                    }
                )
        elif segment.text and segment.text.strip():
            # No word timings (disabled or missing) — use segment span.
            word_level.append(
                {
                    "word": segment.text,
                    "start": segment.start,
                    "end": segment.end,
                }
            )
        if whisper_seg_count % 20 == 0:
            print(
                f"  transcribed {whisper_seg_count} whisper chunks... "
                f"({len(word_level)} tokens, last end={segment.end:.1f}s)"
            )

    segments = segments_to_natural_boundaries(word_level)

    transcript_path = output_dir / "transcript.json"
    with transcript_path.open("w", encoding="utf-8") as f:
        json.dump(segments, f, indent=2, ensure_ascii=False)

    print(
        f"Transcription complete: {len(word_level)} tokens → "
        f"{len(segments)} sentence/pause segments → {transcript_path}"
    )
    return segments
