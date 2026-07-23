"""Tests for Anthropic scoring parse/merge logic (API mocked)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from autocutter.analyze import (
    _normalize_item,
    _parse_scores_json,
    analyze_transcript,
)


def test_normalize_item_clamps_score_and_tags() -> None:
    high = _normalize_item(
        {"id": 1, "score": 99, "reason": "great", "tag": "HOOK", "on_theme": "yes"}
    )
    assert high is not None
    assert high["score"] == 10, f"expected score clamped to 10, got {high['score']}"
    assert high["tag"] == "hook"
    assert high["on_theme"] is True

    low = _normalize_item(
        {"id": 2, "score": -3, "reason": "meh", "tag": "not-a-real-tag", "on_theme": 0}
    )
    assert low is not None
    assert low["score"] == 0, f"expected score clamped to 0, got {low['score']}"
    assert low["tag"] == "filler", f"unknown tag should become filler, got {low['tag']}"
    assert low["on_theme"] is False


def test_normalize_item_rejects_bad_id() -> None:
    assert _normalize_item({"score": 5}) is None
    assert _normalize_item({"id": "x", "score": 5}) is None


def test_parse_scores_json_strips_markdown_fences() -> None:
    payload = [
        {
            "id": 0,
            "score": 8,
            "reason": "hook",
            "tag": "hook",
            "on_theme": False,
        }
    ]
    fenced = f"```json\n{json.dumps(payload)}\n```"
    parsed = _parse_scores_json(fenced)
    assert parsed == payload


def test_analyze_transcript_merges_mocked_api_scores(
    sample_transcript: list[dict[str, Any]],
    mock_anthropic_text_message,
    tmp_path: Path,
) -> None:
    api_payload = [
        {
            "id": 0,
            "score": 7,
            "reason": "greeting",
            "tag": "hook",
            "on_theme": False,
        },
        {
            "id": 1,
            "score": 2,
            "reason": "filler",
            "tag": "filler",
            "on_theme": False,
        },
        {
            "id": 2,
            "score": 9,
            "reason": "punchline",
            "tag": "highlight",
            "on_theme": True,
        },
    ]
    client = MagicMock()
    client.messages.create.return_value = mock_anthropic_text_message(
        json.dumps(api_payload)
    )

    with patch("autocutter.analyze.anthropic.Anthropic", return_value=client):
        result = analyze_transcript(
            sample_transcript,
            api_key="test-key",
            output_dir=tmp_path,
            focus=None,
        )

    assert client.messages.create.called, "expected Anthropic messages.create to be called"
    by_id = {s["id"]: s for s in result}
    assert by_id[0]["score"] == 7
    assert by_id[2]["tag"] == "highlight"
    assert by_id[2]["on_theme"] is True
    assert by_id[0]["start"] == 0.0 and by_id[0]["text"] == "Hello there."

    saved = json.loads((tmp_path / "scored_segments.json").read_text(encoding="utf-8"))
    assert "segments" in saved
    assert len(saved["segments"]) == 3


def test_analyze_transcript_fills_missing_segment_default(
    sample_transcript: list[dict[str, Any]],
    mock_anthropic_text_message,
    tmp_path: Path,
) -> None:
    # API omits segment id 1
    api_payload = [
        {"id": 0, "score": 6, "reason": "ok", "tag": "story", "on_theme": False},
        {"id": 2, "score": 8, "reason": "peak", "tag": "highlight", "on_theme": False},
    ]
    client = MagicMock()
    client.messages.create.return_value = mock_anthropic_text_message(
        json.dumps(api_payload)
    )

    with patch("autocutter.analyze.anthropic.Anthropic", return_value=client):
        result = analyze_transcript(
            sample_transcript, api_key="test-key", output_dir=tmp_path
        )

    missing = next(s for s in result if s["id"] == 1)
    assert missing["score"] == 5, f"missing segment should default to 5, got {missing}"
    assert missing["reason"] == "missing from model response"


def test_analyze_transcript_retries_once_on_bad_json(
    sample_transcript: list[dict[str, Any]],
    mock_anthropic_text_message,
    tmp_path: Path,
) -> None:
    good = [
        {"id": 0, "score": 5, "reason": "a", "tag": "story", "on_theme": False},
        {"id": 1, "score": 5, "reason": "b", "tag": "story", "on_theme": False},
        {"id": 2, "score": 5, "reason": "c", "tag": "story", "on_theme": False},
    ]
    client = MagicMock()
    client.messages.create.side_effect = [
        mock_anthropic_text_message("NOT JSON"),
        mock_anthropic_text_message(json.dumps(good)),
    ]

    with patch("autocutter.analyze.anthropic.Anthropic", return_value=client):
        result = analyze_transcript(
            sample_transcript, api_key="test-key", output_dir=tmp_path
        )

    assert len(result) == 3
    assert client.messages.create.call_count == 2, (
        f"expected one retry after bad JSON, got {client.messages.create.call_count} calls"
    )


def test_analyze_transcript_raises_after_retry_fails(
    sample_transcript: list[dict[str, Any]],
    mock_anthropic_text_message,
    tmp_path: Path,
) -> None:
    client = MagicMock()
    client.messages.create.return_value = mock_anthropic_text_message("{still broken")

    with patch("autocutter.analyze.anthropic.Anthropic", return_value=client):
        with pytest.raises(RuntimeError, match="Failed to parse Claude JSON"):
            analyze_transcript(
                sample_transcript, api_key="test-key", output_dir=tmp_path
            )

    assert client.messages.create.call_count == 2
