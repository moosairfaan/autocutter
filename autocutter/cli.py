#!/usr/bin/env python3
"""autocutter — CLI entry point for AI-assisted video cutting."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import time
from pathlib import Path
from typing import Any, Callable

from dotenv import dotenv_values

from autocutter import AUTOCUTTER_ENV, AUTOCUTTER_HOME
from autocutter.names import video_slug

SKIP_TO_CHOICES = ("transcribe", "analyze", "select")
WHISPER_MODELS = ("tiny", "base", "small", "medium", "large")
API_KEY_NAME = "ANTHROPIC_API_KEY"
_API_KEY_PLACEHOLDERS = frozenset(
    {
        "",
        "your_api_key_here",
        "changeme",
        "sk-ant-...",
        "...",
    }
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Transcribe a video, analyze content, and build an FCPXML cut."
    )
    parser.add_argument(
        "--video",
        type=Path,
        required=True,
        help="Path to the input video file",
    )
    parser.add_argument(
        "--target-minutes",
        type=float,
        default=None,
        help="Desired final runtime in minutes",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="medium",
        help="Whisper model size (default: medium)",
    )
    parser.add_argument(
        "--api-key-env",
        type=str,
        default="ANTHROPIC_API_KEY",
        help="Environment variable name for the Anthropic API key",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("./output"),
        help=(
            "Base directory for outputs (default: ./output). "
            "Each run writes to <output-dir>/<video-slug>/"
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Ignore cached intermediates and re-run extract/transcribe/analyze",
    )
    parser.add_argument(
        "--skip-to",
        choices=SKIP_TO_CHOICES,
        default=None,
        help=(
            "Resume from a cached intermediate in --output-dir: "
            "transcribe (needs audio.wav), analyze (needs transcript.json), "
            "select (needs scored_segments.json). Useful for re-trying "
            "--target-minutes without re-running Whisper or Claude."
        ),
    )
    parser.add_argument(
        "--focus",
        type=str,
        default=None,
        help=(
            "Optional edit theme/angle to weight Claude scoring "
            '(e.g. "Life on Long Island as new grads who also hate it here lol"). '
            "Re-runs analyze when set (unless --skip-to select)."
        ),
    )
    return parser.parse_args()


def _is_usable_api_key(value: str | None) -> bool:
    if value is None:
        return False
    key = value.strip()
    return bool(key) and key.lower() not in _API_KEY_PLACEHOLDERS


def _api_key_from_dotenv(path: Path) -> str | None:
    if not path.is_file():
        return None
    values = dotenv_values(path)
    key = values.get(API_KEY_NAME)
    if isinstance(key, str) and _is_usable_api_key(key):
        return key.strip()
    return None


def _resolve_api_key() -> str | None:
    """Env var → ./.env → ~/.autocutter/.env."""
    env_key = os.environ.get(API_KEY_NAME)
    if isinstance(env_key, str) and _is_usable_api_key(env_key):
        return env_key.strip()

    for path in (Path.cwd() / ".env", AUTOCUTTER_ENV):
        key = _api_key_from_dotenv(path)
        if key:
            os.environ[API_KEY_NAME] = key
            return key
    return None


def _save_api_key(key: str) -> Path:
    """Persist API key to ~/.autocutter/.env (create dir if needed)."""
    AUTOCUTTER_HOME.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    found = False
    if AUTOCUTTER_ENV.is_file():
        for line in AUTOCUTTER_ENV.read_text(encoding="utf-8").splitlines():
            if line.strip().startswith(f"{API_KEY_NAME}="):
                lines.append(f"{API_KEY_NAME}={key}")
                found = True
            else:
                lines.append(line)
    if not found:
        lines.append(f"{API_KEY_NAME}={key}")
    AUTOCUTTER_ENV.write_text("\n".join(lines) + "\n", encoding="utf-8")
    try:
        AUTOCUTTER_ENV.chmod(0o600)
    except OSError:
        pass
    return AUTOCUTTER_ENV


def _prompt_and_store_api_key() -> str:
    from rich.console import Console
    from rich.prompt import Confirm, Prompt

    console = Console()
    console.print(
        "[yellow]No Anthropic API key found.[/yellow]\n"
        f"Checked environment, {Path.cwd() / '.env'}, and {AUTOCUTTER_ENV}."
    )
    while True:
        key = Prompt.ask(
            "[bold cyan]Paste your Anthropic API key[/bold cyan]",
            password=True,
        ).strip()
        if _is_usable_api_key(key):
            break
        console.print("[red]That doesn't look like a valid key. Try again.[/red]")

    os.environ[API_KEY_NAME] = key
    if Confirm.ask(
        f"Save key to [bold]{AUTOCUTTER_ENV}[/bold] so you don't have to re-enter it?",
        default=True,
    ):
        saved = _save_api_key(key)
        console.print(f"[green]Saved[/green] → {saved}")
    else:
        console.print(
            "[dim]Key kept for this run only "
            f"(set {API_KEY_NAME} or create {AUTOCUTTER_ENV} later).[/dim]"
        )
    console.print()
    return key


def ensure_runtime(interactive: bool) -> None:
    """First-run checks: ffmpeg/ffprobe on PATH, then Anthropic API key."""
    missing = [
        name for name in ("ffmpeg", "ffprobe") if shutil.which(name) is None
    ]
    if missing:
        print(
            "ffmpeg not found. Install it with: brew install ffmpeg",
            file=sys.stderr,
        )
        sys.exit(1)

    if _resolve_api_key():
        return

    if interactive:
        try:
            _prompt_and_store_api_key()
        except KeyboardInterrupt:
            print("\nError: interrupted by user.", file=sys.stderr)
            sys.exit(130)
        return

    print(
        f"Error: {API_KEY_NAME} not found.\n"
        "Set it in your environment, or create a .env file with:\n"
        f"  {API_KEY_NAME}=sk-ant-...\n"
        f"Looked in: environment, {Path.cwd() / '.env'}, {AUTOCUTTER_ENV}\n"
        f"Tip: run `autocutter` with no args to paste a key and save it to "
        f"{AUTOCUTTER_ENV}.",
        file=sys.stderr,
    )
    sys.exit(1)


def _normalize_dragged_path(raw: str) -> Path:
    """Clean Terminal drag-and-drop / pasted paths (quotes, escaped spaces)."""
    text = raw.strip()
    if len(text) >= 2 and text[0] == text[-1] and text[0] in {"'", '"'}:
        text = text[1:-1]
    # Terminal escapes spaces and special chars when dragging files in.
    text = (
        text.replace("\\ ", " ")
        .replace("\\(", "(")
        .replace("\\)", ")")
        .replace("\\&", "&")
        .replace("\\'", "'")
        .replace('\\"', '"')
    )
    return Path(text).expanduser()


def _parse_duration_minutes(raw: str) -> float | None:
    """Parse durations like '30m', '45 min', '1h', '1h 30m' into minutes."""
    text = raw.strip().lower()
    if not text:
        return None

    pattern = re.compile(
        r"(\d+(?:\.\d+)?)\s*(hours?|hrs|hr|h|minutes?|mins|min|m)?"
    )
    matches = list(pattern.finditer(text))
    if not matches:
        raise ValueError(f"Could not parse duration: {raw!r}")

    # Reject leftover non-whitespace junk (e.g. "30x").
    leftover = pattern.sub("", text)
    leftover = re.sub(r"[\s,]+", "", leftover)
    if leftover:
        raise ValueError(f"Could not parse duration: {raw!r}")

    total = 0.0
    for match in matches:
        value = float(match.group(1))
        unit = match.group(2)
        if unit is None or unit.startswith("m"):
            total += value
        else:
            total += value * 60
    if total <= 0:
        raise ValueError("Target length must be greater than zero")
    return total


def resolve_run_output_dir(base_dir: Path, video_path: Path) -> Path:
    """Return <base>/<slug>/ for this video (relative to cwd unless base is absolute)."""
    return Path(base_dir) / video_slug(video_path)


def run_interactive() -> argparse.Namespace | None:
    """Guided prompt session when autocutter is run with no arguments."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Confirm, Prompt
    from rich.table import Table

    console = Console()
    console.print()
    console.print(
        Panel.fit(
            "[bold]autocutter[/bold]\nAI-assisted cuts for Final Cut Pro X",
            border_style="cyan",
        )
    )
    console.print()

    while True:
        raw_path = Prompt.ask(
            "[bold cyan]Drag in your video file or paste the path[/bold cyan]"
        )
        video_path = _normalize_dragged_path(raw_path)
        if video_path.is_file():
            break
        console.print(
            f"[red]File not found:[/red] {video_path}\n"
            "Try again (drag from Finder or paste a full path)."
        )

    target_minutes: float | None = None
    while True:
        raw_target = Prompt.ask(
            "[bold cyan]Want to set a target length?[/bold cyan] "
            "(e.g. 30m, or press enter to skip)",
            default="",
            show_default=False,
        )
        if not raw_target.strip():
            break
        try:
            target_minutes = _parse_duration_minutes(raw_target)
            break
        except ValueError as exc:
            console.print(f"[red]{exc}[/red] Try again (e.g. 30m, 45 min, 1h).")

    focus_raw = Prompt.ask(
        "[bold cyan]Any theme or angle you want it to focus on?[/bold cyan] "
        "(press enter to skip)",
        default="",
        show_default=False,
    )
    focus = focus_raw.strip() or None

    model = Prompt.ask(
        "[bold cyan]Whisper model size?[/bold cyan] "
        f"[{'/'.join(WHISPER_MODELS)}]",
        choices=list(WHISPER_MODELS),
        default="medium",
    )

    output_base = Path("./output")
    run_output_dir = resolve_run_output_dir(output_base, video_path)

    console.print()
    table = Table(title="Ready to run", show_header=False, box=None, padding=(0, 2))
    table.add_column(style="dim")
    table.add_column()
    table.add_row("Video", str(video_path.resolve()))
    table.add_row(
        "Target length",
        f"{target_minutes:g} min" if target_minutes is not None else "(skip)",
    )
    table.add_row("Focus", focus if focus else "(skip)")
    table.add_row("Whisper model", model)
    table.add_row("Output folder", str(run_output_dir.resolve()))
    console.print(table)
    console.print()

    if not Confirm.ask("[bold]Run it?[/bold]", default=True):
        console.print("[yellow]Cancelled.[/yellow]")
        return None

    console.print()
    return argparse.Namespace(
        video=video_path,
        target_minutes=target_minutes,
        model=model,
        api_key_env="ANTHROPIC_API_KEY",
        output_dir=output_base,
        force=False,
        skip_to=None,
        focus=focus,
    )


def _cache_fresh(cache_path: Path, source_path: Path | None = None) -> bool:
    """True if cache exists, is non-empty, and is not older than *source_path*."""
    if not cache_path.is_file() or cache_path.stat().st_size == 0:
        return False
    if source_path is not None and source_path.is_file():
        if cache_path.stat().st_mtime < source_path.stat().st_mtime:
            return False
    return True


def _require_cache(path: Path, skip_to: str) -> None:
    if not path.is_file() or path.stat().st_size == 0:
        raise RuntimeError(
            f"--skip-to {skip_to} requires {path}. "
            "Run the earlier pipeline steps once to create it "
            "(or omit --skip-to)."
        )


def _load_json(path: Path) -> Any:
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def _format_duration(seconds: float) -> str:
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(seconds, 60)
    if minutes < 60:
        return f"{int(minutes)}m {secs:.1f}s"
    hours, minutes = divmod(int(minutes), 60)
    return f"{hours}h {minutes}m {secs:.1f}s"


def _run_step(
    step: int,
    total: int,
    title: str,
    fn: Callable[[], Any],
    *,
    skipped: bool = False,
    skip_reason: str = "",
) -> Any:
    header = f"[{step}/{total}] {title}"
    if skipped:
        suffix = f": {skip_reason}" if skip_reason else ""
        print(f"{header} (cached{suffix})")
        t0 = time.perf_counter()
        result = fn()
        elapsed = time.perf_counter() - t0
        print(f"[{step}/{total}] Reused cache in {_format_duration(elapsed)}")
        return result

    print(f"{header}...")
    t0 = time.perf_counter()
    result = fn()
    elapsed = time.perf_counter() - t0
    print(f"[{step}/{total}] Finished in {_format_duration(elapsed)}")
    return result


def run_pipeline(args: argparse.Namespace) -> Path:
    from autocutter.analyze import analyze_transcript, load_scored_file
    from autocutter.build_fcpxml import build_fcpxml, write_report
    from autocutter.extract_audio import extract_audio
    from autocutter.select_segments import select_segments
    from autocutter.transcribe import transcribe

    if args.force and args.skip_to:
        raise RuntimeError("--force and --skip-to cannot be used together")

    video_path = args.video.resolve()
    output_base = Path(args.output_dir)
    output_dir = resolve_run_output_dir(output_base, video_path)
    output_dir.mkdir(parents=True, exist_ok=True)

    audio_path = output_dir / "audio.wav"
    transcript_path = output_dir / "transcript.json"
    scored_path = output_dir / "scored_segments.json"
    fcpxml_path = output_dir / "autocut.fcpxml"

    skip_to = args.skip_to
    focus = args.focus.strip() if isinstance(args.focus, str) and args.focus.strip() else None

    print(f"Output directory: {output_dir.resolve()}")

    # Decide which early steps load from cache vs run.
    # --skip-to explicitly resumes from a stage using its prerequisite file.
    if skip_to == "transcribe":
        _require_cache(audio_path, skip_to)
        load_audio = True
        load_transcript = False
        load_scored = False
    elif skip_to == "analyze":
        _require_cache(transcript_path, skip_to)
        load_audio = True
        load_transcript = True
        load_scored = False
    elif skip_to == "select":
        _require_cache(scored_path, skip_to)
        load_audio = True
        load_transcript = True
        load_scored = True
    else:
        load_audio = (not args.force) and _cache_fresh(audio_path, video_path)
        load_transcript = (
            (not args.force)
            and load_audio
            and _cache_fresh(transcript_path, audio_path)
        )
        load_scored = (
            (not args.force)
            and load_transcript
            and _cache_fresh(scored_path, transcript_path)
        )

    # Reuse scored cache only when saved focus matches this run's focus.
    # (--skip-to select forces reuse even if focus differs.)
    if load_scored and skip_to != "select":
        try:
            _cached_segments, cached_focus = load_scored_file(scored_path)
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            print(f"Cached scores unreadable ({exc}); re-running analyze")
            load_scored = False
        else:
            if cached_focus != focus:
                print(
                    "Focus differs from cached scoring "
                    f"(cached={cached_focus!r}, now={focus!r}); re-running analyze"
                )
                load_scored = False

    api_key = os.environ.get(args.api_key_env)
    if not load_scored and not api_key:
        raise RuntimeError(
            f"Missing API key: set {args.api_key_env} in the environment or .env"
        )

    total_steps = 5
    pipeline_t0 = time.perf_counter()
    if skip_to:
        print(f"Resuming pipeline with --skip-to {skip_to}")

    # --- 1. Extract audio ---
    def step_extract() -> Path:
        if load_audio:
            return audio_path
        return extract_audio(video_path, output_dir)

    audio_path = _run_step(
        1,
        total_steps,
        "Extracting audio",
        step_extract,
        skipped=load_audio,
        skip_reason=(
            f"skipped via --skip-to {skip_to}"
            if skip_to in {"transcribe", "analyze", "select"}
            else str(audio_path)
        ),
    )

    # --- 2. Transcribe ---
    def step_transcribe() -> list[dict[str, Any]]:
        if skip_to == "select":
            # scored_segments.json is enough; transcript not needed downstream.
            return []
        if load_transcript:
            return _load_json(transcript_path)
        return transcribe(audio_path, args.model, output_dir=output_dir)

    transcript = _run_step(
        2,
        total_steps,
        "Transcribing audio",
        step_transcribe,
        skipped=load_transcript,
        skip_reason=(
            f"skipped via --skip-to {skip_to}"
            if skip_to in {"analyze", "select"}
            else str(transcript_path)
        ),
    )

    # --- 3. Analyze ---
    def step_analyze() -> list[dict[str, Any]]:
        if load_scored:
            segments, _cached_focus = load_scored_file(scored_path)
            return segments
        return analyze_transcript(
            transcript,
            api_key=api_key or "",
            output_dir=output_dir,
            focus=focus,
        )

    analyze_title = "Scoring segments with Claude"
    if focus and not load_scored:
        analyze_title += f" (focus: {focus})"

    scored = _run_step(
        3,
        total_steps,
        analyze_title,
        step_analyze,
        skipped=load_scored,
        skip_reason=(
            f"skipped via --skip-to {skip_to}"
            if skip_to == "select"
            else str(scored_path)
        ),
    )

    # --- 4. Select segments ---
    def step_select() -> dict[str, list[dict[str, Any]]]:
        return select_segments(
            scored, target_minutes=args.target_minutes, focus=focus
        )

    select_title = "Selecting segments"
    if args.target_minutes is not None:
        select_title += f" (target {args.target_minutes:g} min)"
    else:
        select_title += " (drop low scores)"
    if focus:
        select_title += ", prefer on_theme"

    selection = _run_step(
        4,
        total_steps,
        select_title,
        step_select,
    )
    kept_segments = selection["kept"]
    cut_segments = selection["cut"]
    print(
        f"         Kept {len(kept_segments)} / cut {len(cut_segments)} "
        f"segments"
    )

    # --- 5. Build FCPXML + report ---
    def step_build() -> tuple[Path, Path]:
        xml_path = build_fcpxml(video_path, kept_segments, fcpxml_path)
        md_path = write_report(kept_segments, cut_segments, output_dir)
        return xml_path, md_path

    fcpxml_path, report_path = _run_step(
        5,
        total_steps,
        "Building FCPXML and edit report",
        step_build,
    )

    total_elapsed = time.perf_counter() - pipeline_t0
    print()
    print("=" * 60)
    print(f"Done in {_format_duration(total_elapsed)}.")
    print(f"  Output folder: {output_dir.resolve()}")
    print(f"  FCPXML:        {fcpxml_path.resolve()}")
    print(f"  Edit report:   {report_path.resolve()}")
    print("Import the .fcpxml into Final Cut Pro X via File > Import > XML.")
    print("=" * 60)
    return output_dir.resolve()


def main() -> None:
    interactive = len(sys.argv) == 1
    ensure_runtime(interactive=interactive)

    if interactive:
        try:
            args = run_interactive()
        except KeyboardInterrupt:
            print("\nError: interrupted by user.", file=sys.stderr)
            sys.exit(130)
        if args is None:
            sys.exit(0)
    else:
        args = parse_args()

    if not args.video.is_file():
        print(f"Error: video not found: {args.video}", file=sys.stderr)
        sys.exit(1)

    try:
        output_dir = run_pipeline(args)
    except KeyboardInterrupt:
        print("\nError: interrupted by user.", file=sys.stderr)
        sys.exit(130)
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        sys.exit(1)

    if interactive:
        from rich.console import Console
        from rich.panel import Panel

        Console().print(
            Panel.fit(
                f"[bold green]Outputs are in[/bold green]\n{output_dir}\n\n"
                "Import [bold]autocut.fcpxml[/bold] into Final Cut Pro X:\n"
                "File → Import → XML",
                border_style="green",
                title="Next step",
            )
        )


if __name__ == "__main__":
    main()
