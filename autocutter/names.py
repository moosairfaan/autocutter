"""Shared naming helpers for CLI and API."""

from __future__ import annotations

import re
from pathlib import Path


def video_slug(video_path: Path | str) -> str:
    """Derive a filesystem-safe slug from the video filename stem.

    Example: ``"nyc vlog.mov"`` → ``"nyc-vlog"``.
    """
    stem = Path(video_path).stem.strip().lower()
    slug = re.sub(r"[^\w]+", "-", stem, flags=re.UNICODE)
    slug = re.sub(r"-+", "-", slug).strip("-_")
    return slug or "video"
