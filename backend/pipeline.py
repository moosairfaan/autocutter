"""Process pipeline (extract → transcribe → analyze → select) with progress events."""

from __future__ import annotations

import json
import os
from typing import Any, Callable

from dotenv import load_dotenv

from autocutter import AUTOCUTTER_ENV
from autocutter.analyze import analyze_transcript, load_scored_file
from autocutter.extract_audio import extract_audio
from autocutter.select_segments import select_segments
from autocutter.transcribe import (
    resolve_whisper_model,
    resolve_word_timestamps,
    transcribe,
)

from backend.storage import (
    build_initial_edit_decision,
    edit_decision_path,
    find_video,
    load_meta,
    project_dir,
    save_meta,
    scored_path,
)

EmitFn = Callable[[dict[str, Any]], None]


def _resolve_api_key() -> str:
    load_dotenv(AUTOCUTTER_ENV)
    load_dotenv()
    key = (os.environ.get("ANTHROPIC_API_KEY") or "").strip()
    if not key or key.lower() in {"your_key_here", "your_api_key_here", "changeme"}:
        raise RuntimeError(
            "ANTHROPIC_API_KEY not set. Add it to the environment or ~/.autocutter/.env"
        )
    return key


def run_process(
    project_id: str,
    *,
    focus: str | None = None,
    target_minutes: float | None = None,
    model: str | None = None,
    word_timestamps: bool | None = None,
    force: bool = False,
    emit: EmitFn | None = None,
) -> dict[str, Any]:
    """Run extract/transcribe/analyze/select; emit SSE-friendly progress dicts."""

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

    root = project_dir(project_id)
    video = find_video(project_id)
    focus = focus.strip() if isinstance(focus, str) and focus.strip() else None

    meta = load_meta(project_id)
    meta["status"] = "processing"
    meta["focus"] = focus
    meta["target_minutes"] = target_minutes
    save_meta(project_id, meta)

    audio_path = root / "audio.wav"
    transcript_path = root / "transcript.json"
    scored = scored_path(project_id)

    try:
        # --- extract ---
        _emit("extract", 0.05, "Extracting audio...")
        if force or not audio_path.is_file() or audio_path.stat().st_size == 0:
            extract_audio(video, root)
        _emit("extract", 0.15, "Audio ready")

        # --- transcribe ---
        resolved_model = resolve_whisper_model(model)
        resolved_wt = resolve_word_timestamps(word_timestamps)
        _emit(
            "transcribe",
            0.18,
            f"Transcribing with Whisper "
            f"(model={resolved_model}, word_timestamps={resolved_wt})...",
        )
        if (
            force
            or not transcript_path.is_file()
            or transcript_path.stat().st_size == 0
            or transcript_path.stat().st_mtime < audio_path.stat().st_mtime
        ):
            transcript = transcribe(
                audio_path,
                model_size=model,
                output_dir=root,
                word_timestamps=word_timestamps,
            )
        else:
            with transcript_path.open(encoding="utf-8") as f:
                transcript = json.load(f)
            _emit("transcribe", 0.50, "Reusing cached transcript")
        _emit("transcribe", 0.55, f"Transcript ready ({len(transcript)} segments)")

        # --- analyze ---
        _emit("analyze", 0.58, "Scoring segments with Claude...")
        reuse_scores = False
        if (
            not force
            and scored.is_file()
            and scored.stat().st_size > 0
            and scored.stat().st_mtime >= transcript_path.stat().st_mtime
        ):
            try:
                segments, cached_focus = load_scored_file(scored)
                if cached_focus == focus:
                    reuse_scores = True
                    _emit("analyze", 0.85, "Reusing cached scores (focus unchanged)")
            except (OSError, ValueError):
                reuse_scores = False

        if not reuse_scores:
            api_key = _resolve_api_key()
            segments = analyze_transcript(
                transcript,
                api_key=api_key,
                output_dir=root,
                focus=focus,
            )
        _emit("analyze", 0.88, f"Scored {len(segments)} segments")

        # --- select ---
        _emit("select", 0.90, "Selecting segments for target length...")
        selection = select_segments(
            segments, target_minutes=target_minutes, focus=focus
        )
        # TEMP DEBUG — keep/cut are decided here (not by Anthropic)
        print(
            f"[DEBUG][select] target_minutes={target_minutes!r} focus={focus!r} "
            f"kept={len(selection['kept'])} cut={len(selection['cut'])}",
            flush=True,
        )
        for s in selection["kept"]:
            print(
                f"[DEBUG][select] KEEP id={s['id']} score={s.get('score')} "
                f"tag={s.get('tag')} {float(s['start']):.3f}-{float(s['end']):.3f}s "
                f"text={s.get('text')!r}",
                flush=True,
            )
        for s in selection["cut"]:
            print(
                f"[DEBUG][select] CUT  id={s['id']} score={s.get('score')} "
                f"tag={s.get('tag')} {float(s['start']):.3f}-{float(s['end']):.3f}s "
                f"text={s.get('text')!r}",
                flush=True,
            )
        kept_ids = {int(s["id"]) for s in selection["kept"]}
        decision = build_initial_edit_decision(segments, kept_ids)
        print(
            f"[DEBUG][select] edit_decision.json seed "
            f"({len(decision.get('segments', []))} segments):",
            flush=True,
        )
        for s in decision.get("segments", []):
            print(
                f"[DEBUG][select] id={s['id']} keep={s['keep']} "
                f"order={s.get('order')} "
                f"trim={s.get('trim_in')}-{s.get('trim_out')}",
                flush=True,
            )
        edit_path = edit_decision_path(project_id)
        with edit_path.open("w", encoding="utf-8") as f:
            json.dump(decision, f, indent=2, ensure_ascii=False)

        meta = load_meta(project_id)
        meta["status"] = "ready"
        meta["kept_count"] = len(selection["kept"])
        meta["cut_count"] = len(selection["cut"])
        save_meta(project_id, meta)

        result = {
            "event": "complete",
            "status": "done",
            "step": "done",
            "progress": 1.0,
            "message": "Processing complete",
            "project_id": project_id,
            "kept_count": len(selection["kept"]),
            "cut_count": len(selection["cut"]),
            "segment_count": len(segments),
        }
        if emit:
            emit(result)
        return result
    except Exception as exc:
        meta = load_meta(project_id)
        meta["status"] = "error"
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
