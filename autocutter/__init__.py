"""autocutter — AI-assisted video cutting for Final Cut Pro X."""

from pathlib import Path

from autocutter.names import video_slug

__version__ = "0.1.0"

# User config, API key, and cached Whisper models live here (not the install dir).
AUTOCUTTER_HOME = Path.home() / ".autocutter"
AUTOCUTTER_ENV = AUTOCUTTER_HOME / ".env"
AUTOCUTTER_MODELS = AUTOCUTTER_HOME / "models"
AUTOCUTTER_PROJECTS = AUTOCUTTER_HOME / "projects"

__all__ = [
    "AUTOCUTTER_ENV",
    "AUTOCUTTER_HOME",
    "AUTOCUTTER_MODELS",
    "AUTOCUTTER_PROJECTS",
    "video_slug",
    "__version__",
]
