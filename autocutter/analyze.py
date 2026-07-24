"""Analyze a transcript with the Anthropic API."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import anthropic

MODEL = "claude-sonnet-4-6"
WINDOW_SECONDS = 12 * 60
OVERLAP_SECONDS = 30
VALID_TAGS = frozenset(
    {
        "hook",
        "insight",
        "story",
        "filler",
        "tangent",
        "repetition",
        "low-energy",
        "dead-air",
        "highlight",
    }
)

BASE_SYSTEM_PROMPT = """You score transcript segments for how interesting / worth-keeping they are in a video edit.

Scoring guidance:
- 8-10: strongest moments — punchlines, key insights, emotional peaks, hooks
- 4-7: solid content, keep unless we need to cut for time
- 0-3: filler, rambling, repetition, dead air, tangents — first to cut

Return ONLY valid JSON, no prose, no markdown fences. Shape:
[
  {"id": <segment_id>, "score": <0-10 int>, "reason": "<short phrase>", "tag": "hook|insight|story|filler|tangent|repetition|low-energy|dead-air|highlight", "on_theme": <boolean>}
]

Score every segment you are given. Use integer scores from 0 to 10 inclusive.
Use exactly one of the allowed tag values for each segment.
Always include "on_theme" as a boolean (true/false) for every segment."""


def _build_system_prompt(focus: str | None) -> str:
    prompt = BASE_SYSTEM_PROMPT
    if not focus:
        prompt += (
            "\n\nNo specific theme was provided. Set on_theme to false for every segment."
        )
        return prompt

    prompt += f"""

The user is editing this footage around a specific theme/angle: '{focus}'. When scoring segments, weight this heavily:
- Segments clearly relevant to this theme (on-topic stories, jokes, moments that support this angle) should score high (7-10), even if they're not otherwise flashy.
- Segments that are off-theme but still generally good content should score medium (4-6).
- Segments that are both off-theme AND low-energy/filler should score low (0-3).
- Add a new boolean field 'on_theme' to each scored segment's JSON output so we can see which segments were kept specifically because they matched the theme.
Set on_theme to true only when the segment clearly supports the theme/angle above; otherwise false."""
    return prompt


def _chunk_segments(
    segments: list[dict[str, Any]],
    window_seconds: float = WINDOW_SECONDS,
    overlap_seconds: float = OVERLAP_SECONDS,
) -> list[list[dict[str, Any]]]:
    """Split segments into ~window_seconds windows with overlap_seconds overlap."""
    if not segments:
        return []

    total_end = max(float(s["end"]) for s in segments)
    step = max(window_seconds - overlap_seconds, 1.0)
    chunks: list[list[dict[str, Any]]] = []
    start = 0.0

    while start < total_end:
        end = start + window_seconds
        chunk = [
            s
            for s in segments
            if float(s["end"]) > start and float(s["start"]) < end
        ]
        if chunk:
            chunks.append(chunk)
        if end >= total_end:
            break
        start += step

    return chunks


def _strip_code_fences(text: str) -> str:
    text = text.strip()
    fence = re.match(r"^```(?:json)?\s*\n?(.*?)\n?```\s*$", text, flags=re.DOTALL | re.IGNORECASE)
    if fence:
        return fence.group(1).strip()
    # Also strip leading/trailing fences if the model wrapped with extra prose nearby.
    text = re.sub(r"^```(?:json)?\s*\n?", "", text, count=1, flags=re.IGNORECASE)
    text = re.sub(r"\n?```$", "", text, count=1)
    return text.strip()


def _parse_scores_json(text: str) -> list[dict[str, Any]]:
    cleaned = _strip_code_fences(text)
    data = json.loads(cleaned)
    if not isinstance(data, list):
        raise ValueError("Expected a JSON array of scored segments")
    return data


def _parse_on_theme(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "y"}
    return False


def _normalize_item(item: dict[str, Any]) -> dict[str, Any] | None:
    try:
        seg_id = int(item["id"])
        score = int(item["score"])
    except (KeyError, TypeError, ValueError):
        return None

    score = max(0, min(10, score))
    reason = str(item.get("reason", "")).strip() or "unspecified"
    tag = str(item.get("tag", "filler")).strip().lower()
    if tag not in VALID_TAGS:
        tag = "filler"
    on_theme = _parse_on_theme(item.get("on_theme", False))

    return {
        "id": seg_id,
        "score": score,
        "reason": reason,
        "tag": tag,
        "on_theme": on_theme,
    }


def _score_chunk(
    client: anthropic.Anthropic,
    chunk: list[dict[str, Any]],
    chunk_index: int,
    total_chunks: int,
    system_prompt: str,
) -> list[dict[str, Any]]:
    payload = [
        {
            "id": s["id"],
            "start": s["start"],
            "end": s["end"],
            "text": s["text"],
        }
        for s in chunk
    ]
    user_prompt = (
        f"Score these transcript segments (chunk {chunk_index + 1}/{total_chunks}). "
        "Return ONLY the JSON array.\n\n"
        f"{json.dumps(payload, ensure_ascii=False)}"
    )

    # TEMP DEBUG — remove after diagnosing filler/pause leakage
    print(
        f"[DEBUG][analyze] chunk {chunk_index + 1}/{total_chunks} "
        f"segment_ids={[s['id'] for s in payload]}",
        flush=True,
    )
    print(
        f"[DEBUG][analyze] chunk {chunk_index + 1} SYSTEM PROMPT:\n"
        f"{system_prompt}",
        flush=True,
    )
    print(
        f"[DEBUG][analyze] chunk {chunk_index + 1} USER PROMPT:\n"
        f"{user_prompt}",
        flush=True,
    )

    def _call() -> str:
        message = client.messages.create(
            model=MODEL,
            max_tokens=8192,
            system=system_prompt,
            messages=[{"role": "user", "content": user_prompt}],
        )
        parts = []
        for block in message.content:
            if getattr(block, "type", None) == "text":
                parts.append(block.text)
        return "".join(parts)

    raw = _call()
    # TEMP DEBUG — Anthropic returns scores/tags, not keep/cut
    print(
        f"[DEBUG][analyze] chunk {chunk_index + 1} RAW API RESPONSE:\n{raw}",
        flush=True,
    )
    try:
        items = _parse_scores_json(raw)
    except (json.JSONDecodeError, ValueError) as first_err:
        print(
            f"  chunk {chunk_index + 1}: JSON parse failed ({first_err}); retrying once..."
        )
        raw = _call()
        print(
            f"[DEBUG][analyze] chunk {chunk_index + 1} RAW API RESPONSE "
            f"(retry):\n{raw}",
            flush=True,
        )
        try:
            items = _parse_scores_json(raw)
        except (json.JSONDecodeError, ValueError) as second_err:
            raise RuntimeError(
                f"Failed to parse Claude JSON for chunk {chunk_index + 1} "
                f"after retry: {second_err}\nRaw response:\n{raw}"
            ) from second_err

    # TEMP DEBUG — parsed JSON before normalize
    print(
        f"[DEBUG][analyze] chunk {chunk_index + 1} PARSED JSON "
        f"({len(items)} items):\n"
        f"{json.dumps(items, indent=2, ensure_ascii=False)}",
        flush=True,
    )

    normalized: list[dict[str, Any]] = []
    for item in items:
        if not isinstance(item, dict):
            print(
                f"[DEBUG][analyze] skipping non-dict parsed item: {item!r}",
                flush=True,
            )
            continue
        norm = _normalize_item(item)
        if norm is not None:
            normalized.append(norm)
        else:
            print(
                f"[DEBUG][analyze] _normalize_item rejected: {item!r}",
                flush=True,
            )
    print(
        f"[DEBUG][analyze] chunk {chunk_index + 1} NORMALIZED "
        f"({len(normalized)} items):\n"
        f"{json.dumps(normalized, indent=2, ensure_ascii=False)}",
        flush=True,
    )
    return normalized


def analyze_transcript(
    segments: list[dict[str, Any]],
    api_key: str,
    output_dir: Path | None = None,
    focus: str | None = None,
) -> list[dict[str, Any]]:
    """Score transcript segments via Claude and save output_dir/scored_segments.json."""
    if output_dir is None:
        output_dir = Path("./output")
    else:
        output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    focus = focus.strip() if isinstance(focus, str) and focus.strip() else None
    system_prompt = _build_system_prompt(focus)

    chunks = _chunk_segments(segments)
    focus_note = f" focus={focus!r}" if focus else ""
    print(
        f"Scoring {len(segments)} segments in {len(chunks)} chunk(s) "
        f"(~{WINDOW_SECONDS // 60} min windows, {OVERLAP_SECONDS}s overlap)"
        f"{focus_note}..."
    )

    client = anthropic.Anthropic(api_key=api_key)
    by_id: dict[int, dict[str, Any]] = {}

    for i, chunk in enumerate(chunks):
        print(
            f"  scoring chunk {i + 1}/{len(chunks)} "
            f"({len(chunk)} segments, "
            f"{float(chunk[0]['start']):.1f}s–{float(chunk[-1]['end']):.1f}s)..."
        )
        scored = _score_chunk(client, chunk, i, len(chunks), system_prompt)
        for item in scored:
            # First score wins for overlapped segments.
            by_id.setdefault(item["id"], item)

    merged: list[dict[str, Any]] = []
    for seg in segments:
        seg_id = int(seg["id"])
        scored = by_id.get(seg_id)
        if scored is None:
            scored = {
                "id": seg_id,
                "score": 5,
                "reason": "missing from model response",
                "tag": "filler",
                "on_theme": False,
            }
            print(
                f"[DEBUG][analyze] segment id={seg_id} missing from API; "
                f"defaulting score=5",
                flush=True,
            )
        merged.append(
            {
                **scored,
                "start": seg["start"],
                "end": seg["end"],
                "text": seg["text"],
            }
        )

    # TEMP DEBUG — final scored table (still scores, not keep/cut)
    print(
        f"[DEBUG][analyze] MERGED scored segments ({len(merged)}):",
        flush=True,
    )
    for s in merged:
        print(
            f"[DEBUG][analyze] id={s['id']} score={s['score']} "
            f"tag={s.get('tag')} on_theme={s.get('on_theme')} "
            f"{float(s['start']):.3f}-{float(s['end']):.3f}s "
            f"text={s.get('text')!r}",
            flush=True,
        )

    out_path = output_dir / "scored_segments.json"
    payload = {"focus": focus, "segments": merged}
    with out_path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    on_theme_count = sum(1 for s in merged if s.get("on_theme"))
    if focus:
        print(f"Scoring complete → {out_path} ({on_theme_count} on_theme)")
    else:
        print(f"Scoring complete → {out_path}")
    return merged


def load_scored_file(path: Path) -> tuple[list[dict[str, Any]], str | None]:
    """Load scored_segments.json; returns (segments, focus).

    Supports the current ``{"focus": ..., "segments": [...]}`` shape and the
    legacy bare list (treated as focus=None).
    """
    with Path(path).open(encoding="utf-8") as f:
        data = json.load(f)

    if isinstance(data, list):
        return data, None
    if isinstance(data, dict) and isinstance(data.get("segments"), list):
        raw_focus = data.get("focus")
        focus = (
            raw_focus.strip()
            if isinstance(raw_focus, str) and raw_focus.strip()
            else None
        )
        return data["segments"], focus
    raise ValueError(
        f"Unrecognized scored_segments.json format in {path} "
        "(expected object with 'segments' or a bare list)"
    )


def analyze(
    transcript: list[dict[str, Any]],
    api_key: str,
    output_dir: Path | None = None,
    focus: str | None = None,
) -> list[dict[str, Any]]:
    """Backward-compatible alias for analyze_transcript."""
    return analyze_transcript(
        transcript, api_key, output_dir=output_dir, focus=focus
    )
