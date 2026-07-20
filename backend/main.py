"""FastAPI app — autocutter backend."""

from __future__ import annotations

import asyncio
import json
import queue
import threading
import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field
from sse_starlette.sse import EventSourceResponse

from autocutter.names import video_slug
from backend.export import load_edit_decision, run_export, validate_edit_decision
from backend.pipeline import run_process
from backend.storage import (
    edit_decision_path,
    export_path,
    find_video,
    load_meta,
    media_type_for,
    project_dir,
    projects_root,
    save_meta,
    scored_path,
    VIDEO_EXTENSIONS,
)

app = FastAPI(title="autocutter", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ProcessBody(BaseModel):
    focus: str | None = None
    target_minutes: float | None = None
    model: str = "medium"
    force: bool = False


class ExportBody(BaseModel):
    clean_audio: bool = False


class EditSegment(BaseModel):
    id: int
    keep: bool
    order: int = -1
    trim_in: float
    trim_out: float
    start: float | None = None
    end: float | None = None
    text: str | None = None
    score: int | None = None
    tag: str | None = None
    on_theme: bool | None = None


class EditDecisionBody(BaseModel):
    segments: list[EditSegment] = Field(min_length=1)


def _sse_from_worker(worker_fn: Any) -> EventSourceResponse:
    """Run a blocking worker in a thread; stream dict events as SSE.

    Always ends with an explicit ``event: complete`` (success) or
    ``event: error`` so clients never hang waiting for a terminal event.
    """
    q: queue.Queue[dict[str, Any] | None] = queue.Queue()

    def target() -> None:
        try:
            worker_fn(q.put)
        except Exception as exc:
            q.put(
                {
                    "event": "error",
                    "step": "error",
                    "progress": 0.0,
                    "message": str(exc),
                    "status": "error",
                }
            )
        finally:
            q.put(None)

    threading.Thread(target=target, daemon=True).start()

    async def event_generator():  # type: ignore[no-untyped-def]
        saw_terminal = False
        try:
            while True:
                item = await asyncio.to_thread(q.get)
                if item is None:
                    break

                raw_event = str(item.get("event", "progress"))
                # Normalize success to SSE event name "complete"
                if raw_event in {"done", "complete"}:
                    saw_terminal = True
                    payload = {
                        **item,
                        "event": "complete",
                        "status": "done",
                        "progress": item.get("progress", 1.0),
                    }
                    yield {
                        "event": "complete",
                        "data": json.dumps(payload),
                    }
                elif raw_event == "error":
                    saw_terminal = True
                    payload = {
                        **item,
                        "event": "error",
                        "status": "error",
                    }
                    yield {
                        "event": "error",
                        "data": json.dumps(payload),
                    }
                else:
                    yield {
                        "event": "progress",
                        "data": json.dumps({**item, "event": "progress"}),
                    }

            # Guarantee a terminal event even if the worker forgot one.
            if not saw_terminal:
                print(
                    "SSE worker finished without terminal event; emitting complete",
                    flush=True,
                )
                yield {
                    "event": "complete",
                    "data": json.dumps(
                        {
                            "event": "complete",
                            "status": "done",
                            "progress": 1.0,
                            "message": "Processing complete",
                        }
                    ),
                }
        except Exception as exc:
            print(f"SSE generator error: {exc}", flush=True)
            yield {
                "event": "error",
                "data": json.dumps(
                    {
                        "event": "error",
                        "status": "error",
                        "step": "error",
                        "progress": 0.0,
                        "message": str(exc),
                    }
                ),
            }
        finally:
            print("SSE stream closed", flush=True)

    return EventSourceResponse(
        event_generator(),
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/projects")
async def create_project(video: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a video; create ~/.autocutter/projects/{id}/ and return project_id.

    Form field name must be ``video`` (matches frontend FormData key).
    """
    import shutil
    from datetime import datetime, timezone

    original = Path(video.filename or "upload.mp4").name
    ext = Path(original).suffix.lower() or ".mp4"
    if ext not in VIDEO_EXTENSIONS and not ext:
        ext = ".mp4"

    # Diagnose before any disk write: what did Starlette/FastAPI actually receive?
    declared_size = getattr(video, "size", None)
    print(
        "UPLOAD recv "
        f"filename={video.filename!r} "
        f"content_type={video.content_type!r} "
        f"declared_size={declared_size!r}",
        flush=True,
    )

    # Read the full body first so we can log exact byte length before writing.
    # (Videos of a few hundred MB are acceptable to hold briefly in memory.)
    payload = await video.read()
    nbytes = len(payload)
    print(f"UPLOAD read {nbytes} bytes from UploadFile before write", flush=True)

    if nbytes == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty (0 bytes read)")
    if nbytes < 1024:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Uploaded file is only {nbytes} bytes — expected a real video. "
                "Check that the frontend FormData field is named 'video' and "
                "appends the File object (not a string/path)."
            ),
        )

    base = video_slug(original)
    project_id = base
    root = projects_root()
    if (root / project_id).exists():
        project_id = f"{base}-{uuid.uuid4().hex[:8]}"

    dest = root / project_id
    dest.mkdir(parents=True, exist_ok=False)
    video_filename = f"source{ext}"
    video_path = dest / video_filename

    try:
        video_path.write_bytes(payload)
        written = video_path.stat().st_size
        print(
            f"UPLOAD wrote {written} bytes → {video_path} "
            f"(match={written == nbytes})",
            flush=True,
        )
        if written != nbytes:
            raise HTTPException(
                status_code=500,
                detail=f"Write size mismatch: read {nbytes}, wrote {written}",
            )
    except HTTPException:
        shutil.rmtree(dest, ignore_errors=True)
        raise
    except Exception as exc:
        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {exc}") from exc
    finally:
        await video.close()

    meta = {
        "id": project_id,
        "original_filename": original,
        "video_filename": video_filename,
        "bytes": nbytes,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "created",
    }
    with (dest / "meta.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return {
        "project_id": project_id,
        "original_filename": original,
        "bytes_written": nbytes,
        "status": "created",
    }


@app.post("/projects/{project_id}/process")
async def process_project(
    project_id: str, body: ProcessBody | None = None
) -> EventSourceResponse:
    """Run extract → transcribe → analyze → select; stream progress via SSE."""
    try:
        project_dir(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    opts = body or ProcessBody()

    def worker(emit: Any) -> None:
        run_process(
            project_id,
            focus=opts.focus,
            target_minutes=opts.target_minutes,
            model=opts.model,
            force=opts.force,
            emit=emit,
        )

    return _sse_from_worker(worker)


@app.get("/projects/{project_id}/segments")
def get_segments(project_id: str) -> dict[str, Any]:
    """Return scored_segments.json (and edit_decision if present)."""
    try:
        project_dir(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    path = scored_path(project_id)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="scored_segments.json not found — run POST /projects/{id}/process first",
        )

    with path.open(encoding="utf-8") as f:
        scored = json.load(f)

    decision = None
    decision_file = edit_decision_path(project_id)
    if decision_file.is_file():
        with decision_file.open(encoding="utf-8") as f:
            decision = json.load(f)

    return {
        "project_id": project_id,
        "scored": scored,
        "edit_decision": decision,
        "meta": load_meta(project_id),
    }


@app.patch("/projects/{project_id}/segments")
def patch_segments(project_id: str, body: EditDecisionBody) -> dict[str, Any]:
    """Save an updated edit decision (keep/cut, trim in/out, order)."""
    try:
        project_dir(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    payload = {"segments": [s.model_dump() for s in body.segments]}
    try:
        # Allow saving with zero kept; still validate trims/order of any kept.
        validate_edit_decision(payload, require_kept=False)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    path = edit_decision_path(project_id)
    with path.open("w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2, ensure_ascii=False)

    meta = load_meta(project_id)
    meta["status"] = "edited"
    save_meta(project_id, meta)

    return {"project_id": project_id, "saved": True, "segment_count": len(body.segments)}


@app.get("/projects/{project_id}/video")
def get_video(project_id: str) -> FileResponse:
    """Stream the original video (HTTP range requests enabled for seeking)."""
    try:
        video = find_video(project_id)
        meta = load_meta(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    return FileResponse(
        path=video,
        media_type=media_type_for(video),
        filename=meta.get("original_filename") or video.name,
        stat_result=video.stat(),
    )


@app.post("/projects/{project_id}/export")
async def export_project(
    project_id: str, body: ExportBody | None = None
) -> EventSourceResponse:
    """Trim + concat kept clips from edit_decision.json; stream export progress via SSE."""
    try:
        project_dir(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    # Validate trims + order before starting SSE so clients get a clear 400
    # instead of a cryptic ffmpeg failure mid-stream.
    try:
        decision = load_edit_decision(project_id)
        validate_edit_decision(decision, require_kept=True)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    opts = body or ExportBody()

    def worker(emit: Any) -> None:
        run_export(project_id, clean_audio=opts.clean_audio, emit=emit)

    return _sse_from_worker(worker)


@app.get("/projects/{project_id}/export/download")
def download_export(project_id: str) -> FileResponse:
    """Serve the finished exported video."""
    try:
        project_dir(project_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    path = export_path(project_id)
    if not path.is_file():
        raise HTTPException(
            status_code=404,
            detail="Export not found — run POST /projects/{id}/export first",
        )

    return FileResponse(
        path=path,
        media_type="video/mp4",
        filename=f"{project_id}-export.mp4",
        stat_result=path.stat(),
    )
