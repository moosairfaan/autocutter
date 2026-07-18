"""Build Final Cut Pro FCPXML from selected segments."""

from __future__ import annotations

import json
import subprocess
import xml.etree.ElementTree as ET
from fractions import Fraction
from pathlib import Path
from typing import Any
from xml.dom import minidom


def seconds_to_fcpxml_time(seconds: float, fps: float) -> str:
    """Convert seconds to FCPXML rational time (e.g. ``150150/30000s``)."""
    if seconds <= 0:
        return "0s"

    frame_num, timescale = _fps_timebase(fps)
    frames = int(round(float(seconds) * float(fps)))
    if frames <= 0:
        return "0s"
    return f"{frames * frame_num}/{timescale}s"


def _fps_timebase(fps: float) -> tuple[int, int]:
    """Return (numerator per frame, timescale) for common frame rates."""
    known = (
        (23.976, 1001, 24000),
        (24.0, 100, 2400),
        (25.0, 100, 2500),
        (29.97, 1001, 30000),
        (30.0, 100, 3000),
        (50.0, 100, 5000),
        (59.94, 1001, 60000),
        (60.0, 100, 6000),
    )
    fps = float(fps)
    best = min(known, key=lambda item: abs(fps - item[0]))
    if abs(fps - best[0]) <= 0.02:
        return best[1], best[2]

    rate = max(int(round(fps)), 1)
    return 100, rate * 100


def _parse_frame_rate(rate: str | None) -> float | None:
    if not rate or rate in {"0/0", "N/A"}:
        return None
    try:
        value = float(Fraction(rate))
    except (ValueError, ZeroDivisionError):
        return None
    return value if value > 0 else None


def detect_video_fps(video_path: Path, fallback: float = 30.0) -> float:
    """Detect video fps via ffprobe; fall back to *fallback* on failure."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=r_frame_rate,avg_frame_rate",
        "-of",
        "json",
        str(video_path),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        print(f"ffprobe not found; using fallback fps={fallback}")
        return float(fallback)

    if result.returncode != 0:
        print(
            f"ffprobe failed (exit {result.returncode}); "
            f"using fallback fps={fallback}\n{result.stderr.strip()}"
        )
        return float(fallback)

    try:
        payload = json.loads(result.stdout)
        stream = (payload.get("streams") or [{}])[0]
    except (json.JSONDecodeError, IndexError, TypeError):
        print(f"Could not parse ffprobe output; using fallback fps={fallback}")
        return float(fallback)

    for key in ("r_frame_rate", "avg_frame_rate"):
        fps = _parse_frame_rate(stream.get(key))
        if fps is not None:
            print(f"Detected video fps via ffprobe: {fps:.3f} ({key})")
            return fps

    print(f"No usable frame rate from ffprobe; using fallback fps={fallback}")
    return float(fallback)


def _probe_video_meta(video_path: Path) -> dict[str, Any]:
    """Return width, height, and duration from ffprobe when available."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,duration",
        "-show_entries",
        "format=duration",
        "-of",
        "json",
        str(video_path),
    ]
    meta: dict[str, Any] = {"width": 1920, "height": 1080, "duration": None}
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError:
        return meta
    if result.returncode != 0:
        return meta

    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return meta

    streams = payload.get("streams") or []
    if streams:
        stream = streams[0]
        if stream.get("width"):
            meta["width"] = int(stream["width"])
        if stream.get("height"):
            meta["height"] = int(stream["height"])
        if stream.get("duration") not in (None, "N/A"):
            try:
                meta["duration"] = float(stream["duration"])
            except (TypeError, ValueError):
                pass

    fmt = payload.get("format") or {}
    if meta["duration"] is None and fmt.get("duration") not in (None, "N/A"):
        try:
            meta["duration"] = float(fmt["duration"])
        except (TypeError, ValueError):
            pass

    return meta


def _file_url(path: Path) -> str:
    """Absolute file:// URL suitable for FCPXML media-rep src."""
    resolved = path.resolve()
    # Path.as_uri() percent-encodes correctly for local paths.
    return resolved.as_uri()


def _format_name(width: int, height: int, fps: float) -> str:
    fps_label_map = (
        (23.976, "2398"),
        (24.0, "24"),
        (25.0, "25"),
        (29.97, "2997"),
        (30.0, "30"),
        (50.0, "50"),
        (59.94, "5994"),
        (60.0, "60"),
    )
    best = min(fps_label_map, key=lambda item: abs(float(fps) - item[0]))
    if abs(float(fps) - best[0]) <= 0.02:
        fps_label = best[1]
    else:
        fps_label = str(int(round(float(fps))))

    if width == 1920 and height == 1080:
        return f"FFVideoFormat1080p{fps_label}"
    if width == 1280 and height == 720:
        return f"FFVideoFormat720p{fps_label}"
    if width == 3840 and height == 2160:
        return f"FFVideoFormat3840x2160p{fps_label}"
    return f"FFVideoFormat{width}x{height}p{fps_label}"


def _format_timestamp(seconds: float) -> str:
    total = max(0, int(round(float(seconds))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:02d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _segment_duration(seg: dict[str, Any]) -> float:
    return max(0.0, float(seg["end"]) - float(seg["start"]))


def build_fcpxml(
    video_path: Path,
    kept_segments: list[dict[str, Any]],
    output_path: Path,
    fps: float = 30,
) -> Path:
    """Generate a valid FCPXML 1.10 file and write it to *output_path*."""
    video_path = Path(video_path).resolve()
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    if not kept_segments:
        raise ValueError("kept_segments is empty; nothing to put on the timeline")

    detected_fps = detect_video_fps(video_path, fallback=float(fps))
    meta = _probe_video_meta(video_path)
    width = int(meta["width"])
    height = int(meta["height"])

    source_duration = meta["duration"]
    if source_duration is None:
        source_duration = max(float(s["end"]) for s in kept_segments)

    frame_num, timescale = _fps_timebase(detected_fps)
    frame_duration = f"{frame_num}/{timescale}s"
    media_url = _file_url(video_path)

    total_kept = sum(_segment_duration(s) for s in kept_segments)
    target_minutes = total_kept / 60.0
    project_name = (
        f"AutoCut - {video_path.name} - {target_minutes:.1f}min"
    )

    # --- Build XML ---
    fcpxml = ET.Element("fcpxml", version="1.10")
    resources = ET.SubElement(fcpxml, "resources")

    ET.SubElement(
        resources,
        "format",
        id="r1",
        name=_format_name(width, height, detected_fps),
        frameDuration=frame_duration,
        width=str(width),
        height=str(height),
    )

    asset = ET.SubElement(
        resources,
        "asset",
        id="r2",
        name=video_path.stem,
        start="0s",
        duration=seconds_to_fcpxml_time(source_duration, detected_fps),
        hasVideo="1",
        hasAudio="1",
        format="r1",
        audioSources="1",
        audioChannels="2",
    )
    ET.SubElement(
        asset,
        "media-rep",
        kind="original-media",
        src=media_url,
    )

    library = ET.SubElement(fcpxml, "library")
    event = ET.SubElement(library, "event", name="AutoCut")
    project = ET.SubElement(event, "project", name=project_name)
    sequence = ET.SubElement(
        project,
        "sequence",
        format="r1",
        duration=seconds_to_fcpxml_time(total_kept, detected_fps),
        tcStart="0s",
        tcFormat="NDF",
        audioLayout="stereo",
        audioRate="48k",
    )
    spine = ET.SubElement(sequence, "spine")

    timeline_offset = 0.0
    for i, seg in enumerate(kept_segments):
        start = float(seg["start"])
        dur = _segment_duration(seg)
        if dur <= 0:
            continue
        clip_name = str(seg.get("tag") or seg.get("reason") or f"Keep {i + 1}")
        ET.SubElement(
            spine,
            "asset-clip",
            ref="r2",
            name=clip_name[:64],
            offset=seconds_to_fcpxml_time(timeline_offset, detected_fps),
            start=seconds_to_fcpxml_time(start, detected_fps),
            duration=seconds_to_fcpxml_time(dur, detected_fps),
            audioRole="dialogue",
        )
        timeline_offset += dur

    # Serialize + validate well-formedness via minidom round-trip.
    rough = ET.tostring(fcpxml, encoding="unicode")
    xml_text = (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        "<!DOCTYPE fcpxml>\n"
        f"{rough}"
    )
    try:
        parsed = minidom.parseString(xml_text)
    except Exception as exc:
        raise RuntimeError(f"Generated FCPXML is not well-formed: {exc}") from exc

    pretty = parsed.toprettyxml(indent="  ", encoding="UTF-8")
    # minidom adds an XML declaration; write bytes directly.
    output_path.write_bytes(pretty)
    print(f"FCPXML written → {output_path}")
    return output_path


def write_report(
    kept_segments: list[dict[str, Any]],
    cut_segments: list[dict[str, Any]],
    output_dir: Path,
) -> Path:
    """Write a markdown edit report listing kept and cut segments."""
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "edit_report.md"

    kept_dur = sum(_segment_duration(s) for s in kept_segments)
    cut_dur = sum(_segment_duration(s) for s in cut_segments)
    source_dur = kept_dur + cut_dur

    lines: list[str] = [
        "# AutoCut Edit Report",
        "",
        f"- Kept: **{len(kept_segments)}** segments ({_format_timestamp(kept_dur)}, "
        f"{kept_dur / 60:.1f} min)",
        f"- Cut: **{len(cut_segments)}** segments ({_format_timestamp(cut_dur)}, "
        f"{cut_dur / 60:.1f} min)",
    ]
    if source_dur > 0:
        lines.append(
            f"- Retention: **{100.0 * kept_dur / source_dur:.1f}%** of scored timeline"
        )
    on_theme_kept = sum(1 for s in kept_segments if s.get("on_theme"))
    on_theme_cut = sum(1 for s in cut_segments if s.get("on_theme"))
    if on_theme_kept or on_theme_cut:
        lines.append(
            f"- On-theme 🎯: **{on_theme_kept}** kept / **{on_theme_cut}** cut"
        )
        lines.append("- Legend: 🎯 = segment marked `on_theme` for the edit focus")
    lines.extend(["", "## Cuts (removed)", ""])

    if not cut_segments:
        lines.append("_No segments were cut._")
    else:
        # Chronological order for sanity-checking.
        ordered_cuts = sorted(cut_segments, key=lambda s: float(s.get("start", 0)))
        for seg in ordered_cuts:
            start = _format_timestamp(float(seg.get("start", 0)))
            end = _format_timestamp(float(seg.get("end", 0)))
            score = seg.get("score", "?")
            reason = str(seg.get("reason") or "n/a").strip()
            tag = str(seg.get("tag") or "").strip()
            text = str(seg.get("text") or "").strip().replace("\n", " ")
            if len(text) > 120:
                text = text[:117] + "..."
            tag_part = f" `{tag}`" if tag else ""
            theme_mark = " 🎯" if seg.get("on_theme") else ""
            lines.append(
                f"- **{start}–{end}**{theme_mark} — score {score}{tag_part}: {reason}"
            )
            if text:
                lines.append(f"  - _{text}_")

    lines.extend(["", "## Kept (on timeline)", ""])
    if not kept_segments:
        lines.append("_No segments kept._")
    else:
        ordered_kept = sorted(kept_segments, key=lambda s: float(s.get("start", 0)))
        timeline_pos = 0.0
        for seg in ordered_kept:
            src_start = _format_timestamp(float(seg.get("start", 0)))
            src_end = _format_timestamp(float(seg.get("end", 0)))
            dur = _segment_duration(seg)
            tl_start = _format_timestamp(timeline_pos)
            tl_end = _format_timestamp(timeline_pos + dur)
            score = seg.get("score", "?")
            reason = str(seg.get("reason") or "n/a").strip()
            tag = str(seg.get("tag") or "").strip()
            tag_part = f" `{tag}`" if tag else ""
            theme_mark = " 🎯" if seg.get("on_theme") else ""
            lines.append(
                f"- **src {src_start}–{src_end}**{theme_mark} → timeline "
                f"{tl_start}–{tl_end} — score {score}{tag_part}: {reason}"
            )
            timeline_pos += dur

    lines.append("")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Edit report written → {report_path}")
    return report_path
