"""Tests for word-level filler detection / clip expansion."""

from __future__ import annotations

from autocutter.filler import (
    expand_clips_with_filler_trims,
    find_filler_cut_ranges,
    keep_slices_after_cuts,
    normalize_token,
)


def test_normalize_token_strips_punct() -> None:
    assert normalize_token(" Um,") == "um"
    assert normalize_token("LIKE") == "like"


def test_always_fillers_cut_inside_kept_window() -> None:
    words = [
        {"word": " Hello", "start": 1.0, "end": 1.3},
        {"word": " um", "start": 1.4, "end": 1.6},
        {"word": " there", "start": 1.7, "end": 2.0},
    ]
    cuts = find_filler_cut_ranges(words, 1.0, 2.0)
    assert len(cuts) == 1, f"expected one um cut, got {cuts}"
    assert cuts[0][0] == 1.4 and cuts[0][1] == 1.6


def test_like_meaningful_not_cut() -> None:
    # Continuous speech: "I like this" — no pause around like
    words = [
        {"word": " I", "start": 0.0, "end": 0.2},
        {"word": " like", "start": 0.21, "end": 0.4},
        {"word": " this", "start": 0.41, "end": 0.7},
    ]
    cuts = find_filler_cut_ranges(words, 0.0, 0.7)
    assert cuts == [], f"meaningful 'like' should not be cut, got {cuts}"


def test_like_filler_cut_near_pause_and_um() -> None:
    words = [
        {"word": " so", "start": 0.0, "end": 0.2},
        {"word": " um", "start": 0.5, "end": 0.7},  # pause before
        {"word": " like", "start": 0.72, "end": 0.9},
        {"word": " yeah", "start": 1.3, "end": 1.5},  # pause after like
    ]
    cuts = find_filler_cut_ranges(words, 0.0, 1.5)
    tokens_cut = []
    for start, end in cuts:
        for w in words:
            if abs(w["start"] - start) < 0.001:
                tokens_cut.append(normalize_token(w["word"]))
    assert "um" in tokens_cut
    assert "like" in tokens_cut, f"filler-like 'like' should be cut, cuts={cuts}"


def test_right_question_not_cut() -> None:
    words = [
        {"word": " okay", "start": 0.0, "end": 0.3},
        {"word": " right?", "start": 0.6, "end": 0.9},  # pause before, but question
    ]
    cuts = find_filler_cut_ranges(words, 0.0, 0.9)
    assert cuts == [], f"'right?' should not be cut, got {cuts}"


def test_expand_clips_splits_around_filler() -> None:
    clips = [{"id": 1, "trim_in": 1.0, "trim_out": 2.0}]
    words = [
        {"word": " Hello", "start": 1.0, "end": 1.3},
        {"word": " uh", "start": 1.4, "end": 1.55},
        {"word": " world", "start": 1.6, "end": 2.0},
    ]
    expanded = expand_clips_with_filler_trims(clips, words)
    assert len(expanded) == 2, f"expected 2 slices, got {expanded}"
    assert expanded[0] == {"id": 1, "trim_in": 1.0, "trim_out": 1.4}
    assert expanded[1]["trim_in"] == 1.55
    assert expanded[1]["trim_out"] == 2.0


def test_expand_noop_without_fillers() -> None:
    clips = [{"id": 3, "trim_in": 5.0, "trim_out": 8.0}]
    words = [
        {"word": " Solid", "start": 5.0, "end": 5.5},
        {"word": " content", "start": 5.55, "end": 6.2},
    ]
    expanded = expand_clips_with_filler_trims(clips, words)
    assert expanded == clips


def test_keep_slices_after_cuts() -> None:
    slices = keep_slices_after_cuts(0.0, 10.0, [(2.0, 3.0), (7.0, 7.5)])
    assert slices == [(0.0, 2.0), (3.0, 7.0), (7.5, 10.0)]
