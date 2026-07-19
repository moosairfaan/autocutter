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
from backend.export import run_export
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
    """Run a blocking worker in a thread; stream dict events as SSE."""
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
                }
            )
        finally:
            q.put(None)

    threading.Thread(target=target, daemon=True).start()

    async def event_generator():  # type: ignore[no-untyped-def]
        while True:
            item = await asyncio.to_thread(q.get)
            if item is None:
                break
            yield {
                "event": item.get("event", "progress"),
                "data": json.dumps(item),
            }

    return EventSourceResponse(event_generator())


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post("/projects")
async def create_project(video: UploadFile = File(...)) -> dict[str, Any]:
    """Upload a video; create ~/.autocutter/projects/{id}/ and return project_id."""
    original = Path(video.filename or "upload.mp4").name
    ext = Path(original).suffix.lower() or ".mp4"
    if ext not in VIDEO_EXTENSIONS:
        # Allow anyway but keep a sane extension for FileResponse media types.
        if not ext:
            ext = ".mp4"

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
        with video_path.open("wb") as out:
            while True:
                chunk = await video.read(1024 * 1024)
                if not chunk:
                    break
                out.write(chunk)
        if video_path.stat().st_size == 0:
            raise HTTPException(status_code=400, detail="Uploaded file is empty")
    except HTTPException:
        raise
    except Exception as exc:
        # Clean up partial project on failure.
        import shutil

        shutil.rmtree(dest, ignore_errors=True)
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {exc}") from exc

    from datetime import datetime, timezone

    meta = {
        "id": project_id,
        "original_filename": original,
        "video_filename": video_filename,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "created",
    }
    with (dest / "meta.json").open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)

    return {
        "project_id": project_id,
        "original_filename": original,
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

    for seg in body.segments:
        if seg.trim_out < seg.trim_in:
            raise HTTPException(
                status_code=400,
                detail=f"Segment {seg.id}: trim_out must be >= trim_in",
            )

    payload = {"segments": [s.model_dump() for s in body.segments]}
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
