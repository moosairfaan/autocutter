"""Export kept clips via ffmpeg filter_complex trim + concat."""

from __future__ import annotations

import json
import shlex
import subprocess
import time
from pathlib import Path
from typing import Any, Callable

from autocutter.filler import (
    expand_clips_with_filler_trims,
    load_words,
    trim_filler_words_enabled,
)
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
    cmd_line = shlex.join(cmd)
    print(f"[export] ffmpeg command:\n{cmd_line}", flush=True)
    print(f"[export] ffmpeg start", flush=True)
    t0 = time.perf_counter()
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "ffmpeg not found. Install it with: brew install ffmpeg"
        ) from exc
    elapsed = time.perf_counter() - t0
    print(
        f"[export] ffmpeg end  duration={elapsed:.2f}s  "
        f"exit={result.returncode}",
        flush=True,
    )
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


def _resolve_trims(seg: dict[str, Any]) -> tuple[float, float]:
    """Read trim bounds from API (trim_in/out) or client camelCase (trimStart/End).

    Never falls back to original start/end — missing trims are an error.
    """
    sid = seg.get("id", "?")
    if "trim_in" in seg and "trim_out" in seg:
        return float(seg["trim_in"]), float(seg["trim_out"])
    if "trimStart" in seg and "trimEnd" in seg:
        return float(seg["trimStart"]), float(seg["trimEnd"])
    raise ValueError(
        f"Segment {sid}: missing trim_in/trim_out (or trimStart/trimEnd)"
    )


def validate_edit_decision(
    decision: dict[str, Any],
    *,
    require_kept: bool = True,
) -> list[dict[str, Any]]:
    """Validate kept segments' trims and order; return clips sorted by ``order``.

    Raises ``ValueError`` with a clear message on:
    - trimEnd/trim_out <= trimStart/trim_in
    - duplicate or gapped ``order`` values among kept segments
      (must be exactly 0..n-1)
    - no kept segments when ``require_kept`` is True
    """
    segments = decision.get("segments")
    if not isinstance(segments, list):
        raise ValueError("edit_decision must contain a 'segments' list")

    kept = [s for s in segments if s.get("keep")]
    if not kept:
        if require_kept:
            raise ValueError("No kept segments to export")
        return []

    problems: list[str] = []
    pending: list[dict[str, Any]] = []

    for seg in kept:
        sid = seg.get("id", "?")
        try:
            trim_in, trim_out = _resolve_trims(seg)
        except (TypeError, ValueError) as exc:
            problems.append(str(exc))
            continue

        if trim_out <= trim_in:
            problems.append(
                f"Segment {sid}: trim_out/trimEnd ({trim_out}) must be greater "
                f"than trim_in/trimStart ({trim_in})"
            )
            continue

        try:
            order = int(seg["order"]) if "order" in seg else -1
        except (TypeError, ValueError):
            problems.append(f"Segment {sid}: order must be an integer")
            continue

        if order < 0:
            problems.append(
                f"Segment {sid}: kept segment has invalid order {order} "
                f"(expected 0..{len(kept) - 1})"
            )
            continue

        try:
            seg_id = int(sid)
        except (TypeError, ValueError):
            problems.append(f"Segment {sid}: id must be an integer")
            continue

        pending.append(
            {
                "id": seg_id,
                "order": order,
                "trim_in": trim_in,
                "trim_out": trim_out,
            }
        )

    if pending:
        orders = [c["order"] for c in pending]
        n = len(pending)
        expected = set(range(n))
        actual = set(orders)

        duplicates = sorted({o for o in orders if orders.count(o) > 1})
        if duplicates:
            problems.append(
                f"Duplicate order values among kept segments: {duplicates}"
            )

        if actual != expected:
            missing = sorted(expected - actual)
            unexpected = sorted(actual - expected)
            bits: list[str] = []
            if missing:
                bits.append(f"missing {missing}")
            if unexpected:
                bits.append(f"unexpected {unexpected}")
            problems.append(
                f"Kept segment order must be contiguous 0..{n - 1} with no "
                f"gaps or duplicates ({', '.join(bits)}; got {sorted(orders)})"
            )

    if problems:
        raise ValueError("Invalid edit decision: " + "; ".join(problems))

    pending.sort(key=lambda c: c["order"])
    return [
        {
            "id": c["id"],
            "trim_in": c["trim_in"],
            "trim_out": c["trim_out"],
        }
        for c in pending
    ]


def kept_clips(decision: dict[str, Any]) -> list[dict[str, Any]]:
    """Kept clips in edit ``order``, using each segment's trim_in/trim_out."""
    return validate_edit_decision(decision, require_kept=True)


# Applied to the concatenated audio when clean_audio=True.
# Order: light denoise → strip only extreme dead air (>2s) → loudness normalize.
AUDIO_CLEANUP_FILTER = (
    "afftdn=nr=8:nf=-25,"
    "silenceremove=start_periods=0:stop_periods=-1:stop_duration=2:"
    "stop_threshold=-50dB:detection=peak,"
    "loudnorm=I=-16:TP=-1.5:LRA=11"
)

# Short-side target pixels for named resolutions (aspect preserved).
RESOLUTION_SHORT_SIDE = {
    "1080p": 1080,
    "720p": 720,
}
VALID_RESOLUTIONS = frozenset({"original", *RESOLUTION_SHORT_SIDE})


def normalize_resolution(raw: str | None) -> str:
    """Return a valid resolution key; unknown values fall back to original."""
    if raw is None or not str(raw).strip():
        return "original"
    key = str(raw).strip().lower()
    if key in VALID_RESOLUTIONS:
        return key
    print(
        f"[export] unrecognized resolution {raw!r}; falling back to original",
        flush=True,
    )
    return "original"


def _probe_video_size(video: Path) -> tuple[int, int]:
    """Return (width, height); (0, 0) if probe fails."""
    cmd = [
        "ffprobe",
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height",
        "-of",
        "csv=p=0",
        str(video),
    ]
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return 0, 0
    if result.returncode != 0 or not result.stdout.strip():
        return 0, 0
    try:
        w_s, h_s = result.stdout.strip().split(",")[:2]
        return int(w_s), int(h_s)
    except (ValueError, TypeError):
        return 0, 0


def scale_filter_expr(resolution: str, width: int, height: int) -> str | None:
    """ffmpeg scale=… that fits the short side to 1080/720, or None for original."""
    if resolution == "original":
        return None
    target = RESOLUTION_SHORT_SIDE.get(resolution)
    if target is None:
        return None
    if width <= 0 or height <= 0:
        # Fallback: assume portrait-style short-side = width (common for phone clips).
        print(
            "[export] could not probe source size; scaling width to "
            f"{target} (height auto)",
            flush=True,
        )
        return f"scale={target}:-2"
    if width >= height:
        # Landscape / square: lock height (classic 1920x1080).
        return f"scale=-2:{target}"
    # Portrait: lock width (e.g. 1080x1920).
    return f"scale={target}:-2"


def build_filter_complex(
    clips: list[dict[str, Any]],
    *,
    has_audio: bool,
    clean_audio: bool = False,
    scale_expr: str | None = None,
) -> str:
    """Build trim/setpts (+ optional scale, atrim) chains and concat in edit order.

    Each clip uses its own trim_in/trim_out (not original start/end). Clip list
    order is the concat sequence (already sorted by ``order``). When
    *scale_expr* is set (e.g. ``scale=1080:-2``), it is applied on each video
    pad after trim/setpts and before concat. Audio filters are never scaled.
    """
    parts: list[str] = []
    concat_pads: list[str] = []

    for i, clip in enumerate(clips):
        start = float(clip["trim_in"])
        end = float(clip["trim_out"])
        vchain = f"trim=start={start:.3f}:end={end:.3f},setpts=PTS-STARTPTS"
        if scale_expr:
            vchain = f"{vchain},{scale_expr}"
        parts.append(f"[0:v]{vchain}[v{i}]")
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
    resolution: str = "original",
) -> list[str]:
    use_cleanup = bool(clean_audio and has_audio)
    resolution = normalize_resolution(resolution)
    scale_expr = None
    if resolution != "original":
        width, height = _probe_video_size(video)
        scale_expr = scale_filter_expr(resolution, width, height)
        print(
            f"[export] resolution={resolution} source={width}x{height} "
            f"scale={scale_expr!r}",
            flush=True,
        )
    filter_complex = build_filter_complex(
        clips,
        has_audio=has_audio,
        clean_audio=use_cleanup,
        scale_expr=scale_expr,
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

    # Fast encode for interactive export; filter_complex path unchanged.
    # (Was -preset medium — that was the main wall-clock cost on short clips.)
    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
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
    resolution: str = "original",
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

    # Optional word-level filler pass (default off — identical to segment-only).
    if trim_filler_words_enabled():
        words = load_words(project_dir(project_id))
        if not words:
            print(
                "[filler] TRIM_FILLER_WORDS=true but words.json missing/empty; "
                "skipping filler pass (re-transcribe with word_timestamps=true)",
                flush=True,
            )
        else:
            before = len(clips)
            clips = expand_clips_with_filler_trims(clips, words)
            print(
                f"[filler] expanded {before} kept segment(s) → {len(clips)} "
                f"ffmpeg trim slice(s)",
                flush=True,
            )
            if not clips:
                raise ValueError(
                    "Filler trimming removed every keep slice — "
                    "disable TRIM_FILLER_WORDS or adjust heuristics"
                )

    # TEMP DEBUG — final cut list handed to ffmpeg (trim_in/out + order)
    print(
        f"[DEBUG][export] edit_decision kept clips for ffmpeg "
        f"({len(clips)}):",
        flush=True,
    )
    for i, clip in enumerate(clips):
        print(
            f"[DEBUG][export] concat[{i}] id={clip.get('id')} "
            f"trim_in={clip.get('trim_in')} trim_out={clip.get('trim_out')} "
            f"duration={float(clip['trim_out']) - float(clip['trim_in']):.3f}s",
            flush=True,
        )
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
            resolution=resolution,
        )
        print(
            f"[DEBUG][export] ffmpeg filter_complex:\n"
            f"{cmd[cmd.index('-filter_complex') + 1] if '-filter_complex' in cmd else '(missing)'}",
            flush=True,
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
