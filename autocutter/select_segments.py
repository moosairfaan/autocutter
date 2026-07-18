"""Select keep segments from analysis to hit a target runtime."""

from __future__ import annotations

from typing import Any


def _duration(seg: dict[str, Any]) -> float:
    return max(0.0, float(seg["end"]) - float(seg["start"]))


def _total_duration(segments: list[dict[str, Any]]) -> float:
    return sum(_duration(s) for s in segments)


def _is_on_theme(seg: dict[str, Any]) -> bool:
    return bool(seg.get("on_theme"))


def select_segments(
    analysis: list[dict[str, Any]],
    target_minutes: float | None = None,
    focus: str | None = None,
) -> dict[str, list[dict[str, Any]]]:
    """Choose segments to keep, optionally constrained by *target_minutes*.

    Returns ``{"kept": [...], "cut": [...]}`` in original chronological order.
    Without a target, drops low scores (0–3) and keeps the rest.
    With a target, repeatedly cuts the lowest-scoring remaining segment until
    the kept runtime fits.

    When *focus* is set, on_theme segments win tie-breaks (cut off-theme first
    among equal scores).
    """
    segments = list(analysis)
    prefer_theme = bool(focus and str(focus).strip())
    if not segments:
        return {"kept": [], "cut": []}

    if target_minutes is None:
        kept = [s for s in segments if int(s.get("score", 0)) >= 4]
        cut = [s for s in segments if int(s.get("score", 0)) < 4]
        if not kept:
            # Avoid an empty timeline if everything scored low.
            kept, cut = segments, []
        return {"kept": kept, "cut": cut}

    target_seconds = float(target_minutes) * 60.0
    remaining_ids = {int(s["id"]) for s in segments}

    # Cut lowest score first. With focus: among equal scores, cut off-theme
    # before on-theme so thematic beats survive the duration trim.
    def cut_key(s: dict[str, Any]) -> tuple[Any, ...]:
        score = int(s.get("score", 0))
        # 0 = off-theme (cut sooner), 1 = on-theme (prefer keep)
        theme_keep_priority = 1 if (prefer_theme and _is_on_theme(s)) else 0
        return (score, theme_keep_priority, -_duration(s), int(s["id"]))

    cut_order = sorted(segments, key=cut_key)

    while True:
        kept = [s for s in segments if int(s["id"]) in remaining_ids]
        if _total_duration(kept) <= target_seconds or len(remaining_ids) <= 1:
            break
        victim = next(
            (s for s in cut_order if int(s["id"]) in remaining_ids),
            None,
        )
        if victim is None:
            break
        remaining_ids.remove(int(victim["id"]))

    kept = [s for s in segments if int(s["id"]) in remaining_ids]
    cut = [s for s in segments if int(s["id"]) not in remaining_ids]
    return {"kept": kept, "cut": cut}
