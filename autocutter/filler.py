"""Word-level filler detection and clip splitting for export.

Runs only when TRIM_FILLER_WORDS is enabled. Does not change segment scoring.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from autocutter import AUTOCUTTER_ENV

# Always treat as filler when they appear as standalone tokens.
ALWAYS_FILLERS = frozenset({"um", "uh", "uhh", "umm"})

# Ambiguous — only cut with pause / filler-neighbor heuristics.
AMBIGUOUS_FILLERS = frozenset({"like", "so", "right"})

# Gap (seconds) between adjacent words that counts as a "pause" for heuristics.
FILLER_PAUSE_GAP_S = 0.28

# Drop keep-slices shorter than this after subtracting fillers.
MIN_KEEP_SLICE_S = 0.05

_TOKEN_RE = re.compile(r"[a-z]+")
_SENTENCE_END_RE = re.compile(r'[.?!]["\')\]]*$')


def trim_filler_words_enabled(explicit: bool | None = None) -> bool:
    """Resolve TRIM_FILLER_WORDS (default false)."""
    if explicit is not None:
        return bool(explicit)
    load_dotenv(AUTOCUTTER_ENV)
    load_dotenv()
    raw = os.environ.get("TRIM_FILLER_WORDS")
    if raw is None or not str(raw).strip():
        return False
    return str(raw).strip().lower() in {"1", "true", "yes", "y", "on"}


def words_path(project_dir: Path) -> Path:
    return Path(project_dir) / "words.json"


def load_words(project_dir: Path) -> list[dict[str, Any]]:
    path = words_path(project_dir)
    if not path.is_file():
        return []
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list):
        return []
    out: list[dict[str, Any]] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        raw = item.get("word", item.get("text", ""))
        if raw is None or not str(raw).strip():
            continue
        try:
            out.append(
                {
                    "word": str(raw),
                    "start": float(item["start"]),
                    "end": float(item["end"]),
                }
            )
        except (KeyError, TypeError, ValueError):
            continue
    return out


def normalize_token(word: str) -> str:
    """Lowercase alphabetic core of a whisper token (strips punct/spaces)."""
    matches = _TOKEN_RE.findall(word.strip().lower())
    return matches[0] if matches else ""


def _ends_sentence(word: str) -> bool:
    return bool(_SENTENCE_END_RE.search(word.strip()))


def _is_question_right(raw: str) -> bool:
    return "right" in raw.lower() and "?" in raw


def find_filler_cut_ranges(
    words: list[dict[str, Any]],
    trim_in: float,
    trim_out: float,
    *,
    pause_gap_s: float = FILLER_PAUSE_GAP_S,
) -> list[tuple[float, float]]:
    """Return (start, end) micro-cuts for fillers inside [trim_in, trim_out]."""
    window = [
        w
        for w in words
        if float(w["end"]) > trim_in and float(w["start"]) < trim_out
    ]
    if not window:
        return []

    n = len(window)
    tokens = [normalize_token(str(w["word"])) for w in window]
    always_mask = [t in ALWAYS_FILLERS for t in tokens]

    def gap_before(i: int) -> float:
        if i <= 0:
            return pause_gap_s + 1.0  # treat window start as a pause edge
        return float(window[i]["start"]) - float(window[i - 1]["end"])

    def gap_after(i: int) -> float:
        if i >= n - 1:
            return pause_gap_s + 1.0
        return float(window[i + 1]["start"]) - float(window[i]["end"])

    def neighbor_always(i: int) -> bool:
        if i > 0 and always_mask[i - 1]:
            return True
        if i + 1 < n and always_mask[i + 1]:
            return True
        return False

    cut_mask = list(always_mask)

    for i, token in enumerate(tokens):
        if token not in AMBIGUOUS_FILLERS:
            continue
        raw = str(window[i]["word"])
        if token == "right" and _is_question_right(raw):
            continue

        pause_neighbor = gap_before(i) > pause_gap_s or gap_after(i) > pause_gap_s
        filler_neighbor = neighbor_always(i)

        # "so" at sentence start (first in window, or after .?!)
        so_sentence_start = False
        if token == "so":
            if i == 0:
                so_sentence_start = True
            elif _ends_sentence(str(window[i - 1]["word"])):
                so_sentence_start = True

        if pause_neighbor or filler_neighbor or so_sentence_start:
            cut_mask[i] = True

    ranges: list[tuple[float, float]] = []
    for i, flag in enumerate(cut_mask):
        if not flag:
            continue
        start = max(trim_in, float(window[i]["start"]))
        end = min(trim_out, float(window[i]["end"]))
        if end - start >= 0.01:
            ranges.append((start, end))

    return _merge_ranges(ranges)


def _merge_ranges(ranges: list[tuple[float, float]]) -> list[tuple[float, float]]:
    if not ranges:
        return []
    ordered = sorted(ranges, key=lambda r: r[0])
    merged: list[list[float]] = [[ordered[0][0], ordered[0][1]]]
    for start, end in ordered[1:]:
        if start <= merged[-1][1] + 0.01:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def keep_slices_after_cuts(
    trim_in: float,
    trim_out: float,
    cut_ranges: list[tuple[float, float]],
    *,
    min_slice_s: float = MIN_KEEP_SLICE_S,
) -> list[tuple[float, float]]:
    """Subtract cut_ranges from [trim_in, trim_out]; return keep slices."""
    if not cut_ranges:
        return [(trim_in, trim_out)]

    slices: list[tuple[float, float]] = []
    cursor = trim_in
    for cut_start, cut_end in _merge_ranges(cut_ranges):
        cut_start = max(trim_in, cut_start)
        cut_end = min(trim_out, cut_end)
        if cut_end <= cut_start:
            continue
        if cut_start - cursor >= min_slice_s:
            slices.append((cursor, cut_start))
        cursor = max(cursor, cut_end)
    if trim_out - cursor >= min_slice_s:
        slices.append((cursor, trim_out))
    return slices


def expand_clips_with_filler_trims(
    clips: list[dict[str, Any]],
    words: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Split each kept clip around filler micro-cuts.

    Output keeps the same ``{id, trim_in, trim_out}`` shape so
    ``build_filter_complex`` stays unchanged — one ffmpeg trim pad per slice.
    """
    if not words:
        return list(clips)

    expanded: list[dict[str, Any]] = []
    for clip in clips:
        trim_in = float(clip["trim_in"])
        trim_out = float(clip["trim_out"])
        seg_id = clip.get("id")
        cuts = find_filler_cut_ranges(words, trim_in, trim_out)
        slices = keep_slices_after_cuts(trim_in, trim_out, cuts)
        if not slices:
            # Degenerate: entire clip was filler — skip rather than emit empty.
            print(
                f"[filler] segment id={seg_id} fully removed by filler trim; skipping",
                flush=True,
            )
            continue
        if len(slices) == 1 and not cuts:
            expanded.append(
                {"id": seg_id, "trim_in": trim_in, "trim_out": trim_out}
            )
            continue
        for start, end in slices:
            expanded.append({"id": seg_id, "trim_in": start, "trim_out": end})
        if cuts:
            print(
                f"[filler] segment id={seg_id}: removed {len(cuts)} filler range(s), "
                f"{len(slices)} keep slice(s)",
                flush=True,
            )
    return expanded
