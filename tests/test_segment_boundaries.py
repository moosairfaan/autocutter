"""Tests for pause / natural-boundary segment splitting."""

from __future__ import annotations

from autocutter.transcribe import segments_to_natural_boundaries


def test_splits_on_inter_word_gap() -> None:
    words = [
        {"word": " Hello", "start": 0.0, "end": 0.3},
        {"word": " there", "start": 0.35, "end": 0.6},
        # 0.5s gap > 0.35 threshold
        {"word": " Friend", "start": 1.1, "end": 1.4},
    ]
    segs = segments_to_natural_boundaries(words)
    assert len(segs) == 2, f"expected gap split, got {segs}"
    assert segs[0]["text"] == "Hello there"
    assert segs[1]["text"] == "Friend"


def test_splits_on_sentence_punct() -> None:
    words = [
        {"word": " Hello.", "start": 0.0, "end": 0.4},
        {"word": " Next", "start": 0.45, "end": 0.7},
    ]
    segs = segments_to_natural_boundaries(words)
    assert len(segs) == 2
    assert segs[0]["text"] == "Hello."


def test_splits_when_whisper_folds_pause_into_long_word() -> None:
    """Zero gaps (common Whisper quirk) but elongated function word = pause."""
    words = [
        {"word": " raw", "start": 11.36, "end": 11.58},
        {"word": " footage", "start": 11.58, "end": 12.10},
        {"word": " right", "start": 12.10, "end": 12.78},
        # 1.06s "and" with only 3 letters — silence absorbed into the token
        {"word": " and", "start": 12.78, "end": 13.84},
        {"word": " sorry", "start": 13.84, "end": 14.44},
        {"word": " let", "start": 14.44, "end": 14.78},
        {"word": " me", "start": 14.78, "end": 14.94},
        {"word": " restart", "start": 14.94, "end": 15.24},
        {"word": " over", "start": 15.24, "end": 15.96},
        {"word": " AutoCutter", "start": 15.96, "end": 16.56},
    ]
    segs = segments_to_natural_boundaries(words)
    texts = [s["text"] for s in segs]
    assert len(segs) >= 2, f"expected long-word splits, got {texts}"
    # Pause after elongated "and" / after "over"
    joined = " || ".join(texts)
    assert "restart over" in joined
    assert any("sorry" in t or "restart over" in t for t in texts)
    assert any(t.startswith("AutoCutter") or "AutoCutter" == t for t in texts) or any(
        "AutoCutter" in t and t.index("AutoCutter") == 0 for t in texts
    )


def test_no_split_on_normal_continuous_speech() -> None:
    words = [
        {"word": " I", "start": 0.0, "end": 0.15},
        {"word": " like", "start": 0.15, "end": 0.35},
        {"word": " this", "start": 0.35, "end": 0.55},
    ]
    segs = segments_to_natural_boundaries(words)
    assert len(segs) == 1
    assert segs[0]["text"] == "I like this"
