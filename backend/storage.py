"""Project storage under ~/.autocutter/projects/{id}/."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from autocutter import AUTOCUTTER_PROJECTS

VIDEO_EXTENSIONS = {".mp4", ".mov", ".m4v", ".mkv", ".avi", ".webm"}


def projects_root() -> Path:
    root = AUTOCUTTER_PROJECTS
    root.mkdir(parents=True, exist_ok=True)
    return root


def project_dir(project_id: str) -> Path:
    path = projects_root() / project_id
    if not path.is_dir():
        raise FileNotFoundError(f"Project not found: {project_id}")
    return path


def meta_path(project_id: str) -> Path:
    return project_dir(project_id) / "meta.json"


def load_meta(project_id: str) -> dict[str, Any]:
    path = meta_path(project_id)
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def save_meta(project_id: str, meta: dict[str, Any]) -> None:
    path = meta_path(project_id)
    with path.open("w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2, ensure_ascii=False)


def find_video(project_id: str) -> Path:
    meta = load_meta(project_id)
    video = project_dir(project_id) / meta["video_filename"]
    if not video.is_file():
        raise FileNotFoundError(f"Video missing for project {project_id}")
    return video


def scored_path(project_id: str) -> Path:
    return project_dir(project_id) / "scored_segments.json"


def edit_decision_path(project_id: str) -> Path:
    return project_dir(project_id) / "edit_decision.json"


def export_path(project_id: str) -> Path:
    return project_dir(project_id) / "export.mp4"


def media_type_for(path: Path) -> str:
    return {
        ".mp4": "video/mp4",
        ".m4v": "video/mp4",
        ".mov": "video/quicktime",
        ".webm": "video/webm",
        ".mkv": "video/x-matroska",
        ".avi": "video/x-msvideo",
    }.get(path.suffix.lower(), "application/octet-stream")


def build_initial_edit_decision(
    scored: list[dict[str, Any]],
    kept_ids: set[int],
) -> dict[str, Any]:
    """Seed edit_decision.json from select_segments keep/cut."""
    kept_chrono = sorted(
        [s for s in scored if int(s["id"]) in kept_ids],
        key=lambda s: float(s["start"]),
    )
    order_by_id = {int(s["id"]): i for i, s in enumerate(kept_chrono)}

    segments: list[dict[str, Any]] = []
    for seg in scored:
        seg_id = int(seg["id"])
        keep = seg_id in kept_ids
        trim_in = float(seg["start"])
        trim_out = float(seg["end"])
        segments.append(
            {
                "id": seg_id,
                "keep": keep,
                "order": order_by_id.get(seg_id, -1),
                "trim_in": trim_in,
                "trim_out": trim_out,
                "start": trim_in,
                "end": trim_out,
                "text": seg.get("text", ""),
                "score": seg.get("score"),
                "tag": seg.get("tag"),
                "on_theme": seg.get("on_theme", False),
            }
        )

    return {"segments": segments}
