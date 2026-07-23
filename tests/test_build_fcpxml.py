"""Tests for FCPXML generation (ffprobe mocked)."""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest

from autocutter.build_fcpxml import build_fcpxml, seconds_to_fcpxml_time


@pytest.fixture
def kept_segments() -> list[dict[str, Any]]:
    return [
        {
            "id": 0,
            "start": 1.0,
            "end": 3.0,
            "text": "Clip A",
            "tag": "hook",
            "reason": "opener",
        },
        {
            "id": 1,
            "start": 10.0,
            "end": 14.0,
            "text": "Clip B",
            "tag": "story",
            "reason": "beat",
        },
    ]


def test_seconds_to_fcpxml_time_known_values() -> None:
    assert seconds_to_fcpxml_time(0, 30.0) == "0s"
    # 1 second at 30fps → 30 frames × 100 / 3000
    assert seconds_to_fcpxml_time(1.0, 30.0) == "3000/3000s"
    assert seconds_to_fcpxml_time(2.0, 30.0) == "6000/3000s"


def test_build_fcpxml_well_formed_and_clip_timings(
    kept_segments: list[dict[str, Any]],
    tmp_path: Path,
) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake")
    out = tmp_path / "cut.fcpxml"

    with (
        patch("autocutter.build_fcpxml.detect_video_fps", return_value=30.0),
        patch(
            "autocutter.build_fcpxml._probe_video_meta",
            return_value={"width": 1920, "height": 1080, "duration": 60.0},
        ),
    ):
        path = build_fcpxml(video, kept_segments, out, fps=30)

    assert path.is_file()
    root = ET.parse(path).getroot()
    assert root.tag == "fcpxml"
    assert root.attrib.get("version") == "1.10"

    clips = root.findall(".//asset-clip")
    assert len(clips) == 2, f"expected 2 asset-clips, got {len(clips)}: {clips}"

    # Durations: 2s and 4s at 30fps → 6000/3000s and 12000/3000s
    assert clips[0].attrib["start"] == seconds_to_fcpxml_time(1.0, 30.0)
    assert clips[0].attrib["duration"] == seconds_to_fcpxml_time(2.0, 30.0)
    assert clips[0].attrib["offset"] == "0s"

    assert clips[1].attrib["start"] == seconds_to_fcpxml_time(10.0, 30.0)
    assert clips[1].attrib["duration"] == seconds_to_fcpxml_time(4.0, 30.0)
    assert clips[1].attrib["offset"] == seconds_to_fcpxml_time(2.0, 30.0)


def test_build_fcpxml_rejects_empty_kept(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake")
    with pytest.raises(ValueError, match="kept_segments is empty"):
        build_fcpxml(video, [], tmp_path / "out.fcpxml")


def test_build_fcpxml_skips_zero_duration_segments(tmp_path: Path) -> None:
    video = tmp_path / "source.mp4"
    video.write_bytes(b"fake")
    segments = [
        {"id": 0, "start": 0.0, "end": 0.0, "text": "empty", "tag": "filler"},
        {"id": 1, "start": 5.0, "end": 7.0, "text": "kept", "tag": "story"},
    ]
    out = tmp_path / "cut.fcpxml"

    with (
        patch("autocutter.build_fcpxml.detect_video_fps", return_value=30.0),
        patch(
            "autocutter.build_fcpxml._probe_video_meta",
            return_value={"width": 1280, "height": 720, "duration": 30.0},
        ),
    ):
        build_fcpxml(video, segments, out)

    clips = ET.parse(out).getroot().findall(".//asset-clip")
    assert len(clips) == 1, f"zero-duration clip should be skipped, got {len(clips)}"
    assert clips[0].attrib["start"] == seconds_to_fcpxml_time(5.0, 30.0)
