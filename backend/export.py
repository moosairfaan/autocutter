"""Export kept clips via ffmpeg filter_complex trim + concat."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any, Callable

from backend.storage import (
    edit_decision_path,
    export_path,
    find_video,
    load_meta,
    project_dir,
    save_meta,
)

EmitFn = Callable[[dict[str, Any]], None]


def _run_ffprobe_has_audio(video: Path) -> bool:
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "a:0",
        "-show_entries",
        "stream=index",
        "-of",
        "csv=p=0",
        str(video),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffprobe not found. Install it with: brew install ffmpeg"
        ) from exc
    return result.returncode == 0 and bool(result.stdout.strip())


def _run_ffmpeg(cmd: list[str]) -> None:
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg not found. Install it with: brew install ffmpeg"
        ) from exc
    if result.returncode != 0:
        raise RuntimeError(
            f"ffmpeg failed (exit {result.returncode}):\n{result.stderr.strip()}"
        )


def load_edit_decision(project_id: str) -> dict[str, Any]:
    path = edit_decision_path(project_id)
    if not path.is_file():
        raise FileNotFoundError(
            "edit_decision.json not found — process the project and save an edit first"
        )
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not isinstance(data.get("segments"), list):
        raise ValueError("edit_decision.json must be an object with a 'segments' list")
    return data


def kept_clips(decision: dict[str, Any]) -> list[dict[str, Any]]:
    kept = [s for s in decision["segments"] if s.get("keep")]
    kept.sort(key=lambda s: (int(s.get("order", 0)), float(s.get("trim_in", 0))))
    clips: list[dict[str, Any]] = []
    for seg in kept:
        trim_in = float(seg["trim_in"])
        trim_out = float(seg["trim_out"])
        if trim_out <= trim_in:
            continue
        clips.append(
            {
                "id": int(seg["id"]),
                "trim_in": trim_in,
                "trim_out": trim_out,
            }
        )
    if not clips:
        raise ValueError("No kept segments with valid trim_in/trim_out to export")
    return clips


# Applied to the concatenated audio when clean_audio=True.
# Order: light denoise → strip only extreme dead air (>2s) → loudness normalize.
AUDIO_CLEANUP_FILTER = (
    "afftdn=nr=8:nf=-25,"
    "silenceremove=start_periods=0:stop_periods=-1:stop_duration=2:"
    "stop_threshold=-50dB:detection=peak,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)


def build_filter_complex(
    clips: list[dict[str, Any]],
    *,
    has_audio: bool,
    clean_audio: bool = False,
) -> str:
    """Build trim/setpts (+ atrim) chains and a final concat for edit order."""
    parts: list[str] = []
    concat_pads: list[str] = []

    for i, clip in enumerate(clips):
        start = float(clip["trim_in"])
        end = float(clip["trim_out"])
        parts.append(
            f"[0:v]trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS[v{i}]"
        )
        if has_audio:
            parts.append(
                f"[0:a]atrim=start={start:.3f}:end={end:.3f},asetpts=PTS-STARTPTS[a{i}]"
            )
            concat_pads.append(f"[v{i}][a{i}]")
        else:
            concat_pads.append(f"[v{i}]")

    n = len(clips)
    if has_audio:
        parts.append("".join(concat_pads) + f"concat=n={n}:v=1:a=1[outv][outa]")
        if clean_audio:
            parts.append(f"[outa]{AUDIO_CLEANUP_FILTER}[outa_clean]")
    else:
        parts.append("".join(concat_pads) + f"concat=n={n}:v=1:a=0[outv]")
    return ";".join(parts)


def build_export_command(
    video: Path,
    out: Path,
    clips: list[dict[str, Any]],
    *,
    has_audio: bool,
    clean_audio: bool = False,
) -> list[str]:
    use_cleanup = bool(clean_audio and has_audio)
    filter_complex = build_filter_complex(
        clips, has_audio=has_audio, clean_audio=use_cleanup
    )
    audio_label = "[outa_clean]" if use_cleanup else "[outa]"
    cmd = [
        "ffmpeg",
        "-y",
        "-i",
        str(video),
        "-filter_complex",
        filter_complex,
        "-map",
        "[outv]",
    ]
    if has_audio:
        cmd.extend(["-map", audio_label])

    # High-quality H.264/AAC for further editing downstream.
    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "medium",
            "-crf",
            "16",
            "-b:v",
            "12M",
            "-maxrate",
            "16M",
            "-bufsize",
            "24M",
            "-pix_fmt",
            "yuv420p",
        ]
    )
    if has_audio:
        cmd.extend(["-c:a", "aac", "-b:a", "320k"])
    cmd.extend(["-movflags", "+faststart", str(out)])
    return cmd


def run_export(
    project_id: str,
    *,
    clean_audio: bool = False,
    emit: EmitFn | None = None,
) -> dict[str, Any]:
    """Trim + concat kept clips into project export.mp4; emit progress events."""

    def _emit(step: str, progress: float, message: str = "", **extra: Any) -> None:
        if emit:
            emit(
                {
                    "event": "progress",
                    "step": step,
                    "progress": round(max(0.0, min(1.0, progress)), 3),
                    "message": message,
                    **extra,
                }
            )

    video = find_video(project_id)
    decision = load_edit_decision(project_id)
    clips = kept_clips(decision)
    out = export_path(project_id)

    meta = load_meta(project_id)
    meta["status"] = "exporting"
    meta["clean_audio"] = bool(clean_audio)
    save_meta(project_id, meta)

    try:
        total = len(clips)
        _emit("export", 0.05, f"Building filter graph for {total} clip(s)...")
        has_audio = _run_ffprobe_has_audio(video)
        if clean_audio and not has_audio:
            _emit("export", 0.08, "Clean audio requested but source has no audio track")
        cmd = build_export_command(
            video,
            out,
            clips,
            has_audio=has_audio,
            clean_audio=clean_audio,
        )

        cleanup_note = ", audio cleanup on" if (clean_audio and has_audio) else ""
        _emit(
            "export",
            0.15,
            f"Rendering frame-accurate export ({total} segments, "
            f"{'video+audio' if has_audio else 'video only'}{cleanup_note})...",
        )
        _run_ffmpeg(cmd)
        _emit("export", 0.95, "Finalizing export...")

        if not out.is_file() or out.stat().st_size == 0:
            raise RuntimeError("Export finished but output file is missing or empty")

        meta = load_meta(project_id)
        meta["status"] = "exported"
        meta["export_filename"] = out.name
        save_meta(project_id, meta)

        result = {
            "event": "complete",
            "status": "done",
            "step": "done",
            "progress": 1.0,
            "message": "Export complete",
            "project_id": project_id,
            "export_path": str(out),
            "clip_count": total,
            "clean_audio": bool(clean_audio and has_audio),
        }
        if emit:
            emit(result)
        return result
    except Exception as exc:
        meta = load_meta(project_id)
        meta["status"] = "export_error"
        meta["error"] = str(exc)
        save_meta(project_id, meta)
        if emit:
            emit(
                {
                    "event": "error",
                    "status": "error",
                    "step": "error",
                    "progress": 0.0,
                    "message": str(exc),
                }
            )
        raise
