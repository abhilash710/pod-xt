#!/usr/bin/env python3
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
import sys
from typing import Any, Dict, List, Optional

# Use rich-click for colorized --help when available
try:  # pragma: no cover
    import click  # type: ignore
    import rich_click  # type: ignore

    # Style configuration (approximate the standard color convention)
    rc = rich_click.rich_click
    rc.STYLE_HEADING = "bold bright_green"
    rc.STYLE_USAGE = "bold white"
    rc.STYLE_COMMAND = "bold white"
    rc.STYLE_METAVAR = "yellow"
    rc.STYLE_SWITCH = "bright_black"  # flags
    rc.STYLE_OPTION = "bright_black"  # flags
    rc.STYLE_ARGUMENT = "yellow"  # flag arguments
    rc.STYLE_HELP = "white"
    rc.GROUP_ARGUMENTS_OPTIONS = True
    rc.MAX_WIDTH = 100

    BaseGroup = rich_click.RichGroup
except Exception:  # pragma: no cover
    import click  # type: ignore
    BaseGroup = click.Group

# Import individual command modules for CLI integration
from . import (
    deepcast,
    diarize,
    export,
    fetch,
    notion,
    transcode,
    transcribe,
)
from .config import get_config
from .constants import (
    DEFAULT_ENCODING,
    JSON_INDENT,
    MIN_NOTION_DB_ID_LENGTH,
    OPENAI_MODEL_PREFIX,
    PREVIEW_MAX_LENGTH,
    TITLE_MAX_LENGTH,
)
from .errors import ValidationError
from .help import help_cmd
from .logging import get_logger, setup_logging
from .plugins import PluginManager, PluginType, get_registry
from .progress import (
    PodxProgress,
    print_podx_header,
)
from .yaml_config import get_yaml_config_manager

# Initialize logging
setup_logging()
logger = get_logger(__name__)



def _run(
    cmd: List[str],
    stdin_payload: Optional[Dict[str, Any]] = None,
    verbose: bool = False,
    save_to: Optional[Path] = None,
    label: Optional[str] = None,
) -> Dict[str, Any]:
    """Run a CLI tool that prints JSON to stdout; return parsed dict."""
    if label:
        logger.debug("Running command", command=" ".join(cmd), label=label)

    proc = subprocess.run(
        cmd,
        input=json.dumps(stdin_payload) if stdin_payload else None,
        text=True,
        capture_output=True,
    )

    if proc.returncode != 0:
        err = proc.stderr.strip() or proc.stdout.strip()
        logger.error(
            "Command failed",
            command=" ".join(cmd),
            return_code=proc.returncode,
            error=err,
        )
        raise ValidationError(f"Command failed: {' '.join(cmd)}\n{err}")

    # stdout should be JSON; optionally mirror to console
    out = proc.stdout

    if verbose:
        # Show a compact preview of the JSON output
        preview = out[:PREVIEW_MAX_LENGTH] + "..." if len(out) > PREVIEW_MAX_LENGTH else out
        click.secho(preview, fg="white")

    try:
        data = json.loads(out)
        logger.debug("Command completed successfully", command=cmd[0])
    except json.JSONDecodeError:
        # Some subcommands (e.g., deepcast/notion) print plain text "Wrote: ..."
        data = {"stdout": out.strip()}
        logger.debug("Command returned non-JSON output", command=cmd[0])

    if save_to:
        save_to.write_text(out, encoding=DEFAULT_ENCODING)
        logger.debug("Output saved", file=str(save_to))

    return data


def _run_passthrough(cmd: List[str]) -> int:
    """Run a CLI tool in passthrough mode (inherit stdio). Returns returncode.

    Use this for interactive child processes so the user sees the UI and can interact.
    """
    proc = subprocess.run(cmd)
    return proc.returncode


class PodxGroup(BaseGroup):
    """Custom group to hide deprecated commands from help."""

    def list_commands(self, ctx):  # type: ignore[override]
        commands = super().list_commands(ctx)
        # Filter hidden and deprecated workflow aliases from help
        hidden_names = {"quick", "analyze", "publish"}
        return [name for name in commands if name not in hidden_names]


@click.group(cls=PodxGroup)
def main():
    """Podx — composable podcast pipeline

    Core idea: small tools that do one thing well and compose cleanly.

    Core commands (composable):
      fetch, transcode, transcribe, preprocess, align, diarize, export, deepcast, agreement, consensus, notion

    Orchestrator:
      run  — drive the pipeline end‑to‑end with flags (or interactive mode)

    Tips:
    - Use 'podx COMMAND --help' for details on each tool
    - Use 'podx help --examples' for copy‑paste examples
    - All tools read JSON from stdin and write JSON to stdout so you can pipe them
    """
    pass


def _build_pipeline_config(
    show: Optional[str],
    rss_url: Optional[str],
    youtube_url: Optional[str],
    date: Optional[str],
    title_contains: Optional[str],
    workdir: Optional[Path],
    fmt: str,
    model: str,
    compute: str,
    asr_provider: str,
    preprocess: bool,
    restore: bool,
    diarize: bool,
    deepcast: bool,
    deepcast_model: str,
    deepcast_temp: float,
    extract_markdown: bool,
    deepcast_pdf: bool,
    notion: bool,
    notion_db: Optional[str],
    podcast_prop: str,
    date_prop: str,
    episode_prop: str,
    model_prop: str,
    asr_prop: str,
    append_content: bool,
    full: bool,
    verbose: bool,
    clean: bool,
    no_keep_audio: bool,
) -> Dict[str, Any]:
    """Build pipeline configuration from CLI arguments.

    Applies preset transformations (--full) to CLI flags
    and returns a configuration dictionary ready for pipeline execution.

    Args:
        All CLI arguments from run() function

    Returns:
        Configuration dictionary with processed flags
    """
    # Start with all arguments in a dict (will be modified by presets)
    config = {
        "show": show,
        "rss_url": rss_url,
        "youtube_url": youtube_url,
        "date": date,
        "title_contains": title_contains,
        "workdir": workdir,
        "fmt": fmt,
        "model": model,
        "compute": compute,
        "asr_provider": asr_provider,
        "preprocess": preprocess,
        "restore": restore,
        "diarize": diarize,
        "deepcast": deepcast,
        "deepcast_model": deepcast_model,
        "deepcast_temp": deepcast_temp,
        "extract_markdown": extract_markdown,
        "deepcast_pdf": deepcast_pdf,
        "notion": notion,
        "notion_db": notion_db,
        "podcast_prop": podcast_prop,
        "date_prop": date_prop,
        "episode_prop": episode_prop,
        "model_prop": model_prop,
        "asr_prop": asr_prop,
        "append_content": append_content,
        "verbose": verbose,
        "clean": clean,
        "no_keep_audio": no_keep_audio,
        "yaml_analysis_type": None,  # Will be set by interactive mode or workflow
    }

    # Handle convenience --full flag
    if full:
        config["deepcast"] = True
        config["extract_markdown"] = True
        config["notion"] = True

    return config


def _execute_fetch(
    config: dict,
    interactive_mode_meta: dict | None,
    interactive_mode_wd: Path | None,
    progress,
    verbose: bool,
) -> tuple[dict, Path]:
    """Execute fetch step to get episode metadata and determine working directory.

    Handles three fetch modes:
    1. Interactive mode: Use pre-loaded metadata and workdir (skip fetch)
    2. YouTube mode: Fetch from YouTube URL
    3. RSS/Podcast mode: Fetch from iTunes search or RSS feed

    After fetching, applies podcast-specific configuration from YAML/JSON config.

    Args:
        config: Pipeline configuration dictionary (modified in place for podcast config)
        interactive_mode_meta: Pre-loaded metadata from interactive selection (or None)
        interactive_mode_wd: Pre-determined workdir from interactive selection (or None)
        progress: Progress tracker instance
        verbose: Enable verbose logging

    Returns:
        Tuple of (episode_metadata, working_directory)

    Raises:
        ValidationError: If no source (show/RSS/YouTube) is provided
        SystemExit: On fetch failures
    """
    # 1. Interactive mode: metadata and workdir already determined
    if interactive_mode_meta is not None and interactive_mode_wd is not None:
        # Check if audio file exists; if not, need to fetch
        audio_path = interactive_mode_meta.get("audio_path")
        if audio_path and Path(audio_path).exists():
            return interactive_mode_meta, interactive_mode_wd

        # Audio missing - populate config from metadata and fall through to fetch
        if interactive_mode_meta.get("show"):
            config["show"] = interactive_mode_meta["show"]
        if interactive_mode_meta.get("episode_published"):
            config["date"] = interactive_mode_meta["episode_published"]
        if interactive_mode_meta.get("episode_title"):
            config["title_contains"] = interactive_mode_meta["episode_title"]
        if interactive_mode_meta.get("feed"):
            config["rss_url"] = interactive_mode_meta["feed"]

        # Use the selected episode's workdir instead of generating a new one
        config["workdir"] = interactive_mode_wd

    # 2. YouTube URL mode
    if config.get("youtube_url"):
        from .youtube import (
            get_youtube_metadata,
            is_youtube_url,
        )

        youtube_url = config["youtube_url"]
        if not is_youtube_url(youtube_url):
            raise ValidationError(f"Invalid YouTube URL: {youtube_url}")

        progress.start_step("Fetching YouTube video metadata")

        # Get metadata first to determine workdir
        youtube_metadata = get_youtube_metadata(youtube_url)

        # Create metadata dict
        meta = {
            "show": youtube_metadata["channel"],
            "episode_title": youtube_metadata["title"],
            "episode_published": youtube_metadata.get("upload_date", ""),
        }

        progress.complete_step(
            f"YouTube metadata fetched: {meta.get('episode_title', 'Unknown')[:TITLE_MAX_LENGTH]}"
        )

        # Note: YouTube audio will be downloaded after workdir is created
        # (handled by run() function after _execute_fetch returns)

    # 3. RSS/Podcast mode
    else:
        from .services import CommandBuilder

        fetch_cmd = CommandBuilder("podx-fetch")
        if config.get("show"):
            fetch_cmd.add_option("--show", config["show"])
        elif config.get("rss_url"):
            fetch_cmd.add_option("--rss-url", config["rss_url"])
        else:
            raise ValidationError(
                "Either --show, --rss-url, or --youtube-url must be provided."
            )

        if config.get("date"):
            fetch_cmd.add_option("--date", config["date"])
        if config.get("title_contains"):
            fetch_cmd.add_option("--title-contains", config["title_contains"])
        if config.get("workdir"):
            fetch_cmd.add_option("--outdir", str(config["workdir"]))

        # Run fetch first to get metadata
        progress.start_step("Fetching episode metadata")
        meta = _run(
            fetch_cmd.build(),
            verbose=verbose,
            save_to=None,  # Don't save yet, we'll save after determining workdir
            label=None,  # Progress handles the display
        )
        progress.complete_step(
            f"Episode fetched: {meta.get('episode_title', 'Unknown')}"
        )

    # 4. Apply podcast-specific configuration from YAML/JSON
    from .utils import apply_podcast_config

    show_name = meta.get("show") or meta.get("show_name", "")

    # Current flags to potentially override
    current_flags = {
        "diarize": config["diarize"],
        "deepcast": config["deepcast"],
        "extract_markdown": config["extract_markdown"],
        "notion": config["notion"],
    }

    config_result = apply_podcast_config(
        show_name=show_name,
        current_flags=current_flags,
        deepcast_model=config["deepcast_model"],
        deepcast_temp=config["deepcast_temp"],
        notion=config["notion"],
        logger=logger,
    )

    # Update config with podcast-specific overrides
    config["diarize"] = config_result.flags["diarize"]
    config["deepcast"] = config_result.flags["deepcast"]
    config["extract_markdown"] = config_result.flags["extract_markdown"]
    config["notion"] = config_result.flags["notion"]
    config["deepcast_model"] = config_result.deepcast_model
    config["deepcast_temp"] = config_result.deepcast_temp
    config["yaml_analysis_type"] = config_result.yaml_analysis_type

    # 5. Determine working directory
    if config.get("workdir"):
        wd = config["workdir"]
    else:
        from .utils import generate_workdir

        show = meta.get("show", "Unknown Show")
        episode_date = meta.get("episode_published") or config.get("date") or "unknown"
        wd = generate_workdir(show, episode_date)

    return meta, wd


def _execute_transcribe(
    model: str,
    compute: str,
    asr_provider: str,
    audio: dict,
    wd: Path,
    progress,
    verbose: bool,
) -> tuple[dict, str]:
    """Execute transcription step.

    Handles transcript discovery and resume support.

    Args:
        model: ASR model name (e.g., "large-v3")
        compute: Compute type (int8, float16, float32)
        asr_provider: ASR provider (auto, local, openai, hf)
        audio: Audio metadata dict from transcode step
        wd: Working directory Path
        progress: Progress tracker instance
        verbose: Enable verbose logging

    Returns:
        Tuple of (latest_transcript_dict, latest_transcript_name)
        - latest_transcript_dict: JSON data of the latest transcript
        - latest_transcript_name: Filename without .json extension

    Resume Support:
        - Reuses existing transcripts for the same model
        - Falls back to best available model if exact match not found
    """
    import json
    import time

    from .utils import discover_transcripts, sanitize_model_name

    existing_transcripts = discover_transcripts(wd)

    # Proposed output filename (sanitized model to avoid colons/spaces)
    transcript_file = wd / f"transcript-{sanitize_model_name(model)}.json"

    # Check legacy transcript.json
    legacy_transcript = wd / "transcript.json"
    if legacy_transcript.exists():
        try:
            legacy_data = json.loads(legacy_transcript.read_text())
            legacy_model = legacy_data.get("asr_model", "unknown")
            existing_transcripts[legacy_model] = legacy_transcript
        except Exception:
            existing_transcripts["unknown"] = legacy_transcript

    if transcript_file.exists():
        # Use existing transcript for this specific model
        logger.info(
            f"Found existing transcript for model {model}, skipping transcription"
        )
        base = json.loads(transcript_file.read_text())
        progress.complete_step(
            f"Using existing transcript ({model}) - {len(base.get('segments', []))} segments",
            0,
        )
    elif existing_transcripts:
        # Found transcripts with other models - pick the most sophisticated among known order
        order = ["tiny", "base", "small", "medium", "large", "large-v2", "large-v3"]
        available = list(existing_transcripts.keys())
        best = None
        for m in reversed(order):
            if m in available:
                best = m
                break
        best_model = best or available[0]

        logger.info(f"Found existing transcript with model {best_model}, using it")
        base = json.loads(existing_transcripts[best_model].read_text())
        progress.complete_step(
            f"Using existing transcript ({best_model}) - {len(base.get('segments', []))} segments",
            0,
        )
    else:
        # Single track transcription
        progress.start_step(f"Transcribing with {model} model")
        step_start = time.time()
        from .services import CommandBuilder

        transcribe_cmd = (
            CommandBuilder("podx-transcribe")
            .add_option("--model", model)
            .add_option("--compute", compute)
        )
        if asr_provider and asr_provider != "auto":
            # Convert asr_provider enum to string value if needed
            asr_provider_value = asr_provider.value if hasattr(asr_provider, 'value') else asr_provider
            transcribe_cmd.add_option("--asr-provider", asr_provider_value)

        base = _run(
            transcribe_cmd.build(),
            stdin_payload=audio,
            verbose=verbose,
            save_to=transcript_file,
            label=None,
        )
        step_duration = time.time() - step_start
        progress.complete_step(
            f"Transcription complete - {len(base.get('segments', []))} segments",
            step_duration,
        )

    # Set latest and latest_name
    latest = base
    latest_name = f"transcript-{base.get('asr_model', model)}"
    return latest, latest_name


def _execute_enhancement(
    preprocess: bool,
    restore: bool,
    diarize: bool,
    model: str,
    latest: dict,
    latest_name: str,
    wd: Path,
    progress,
    verbose: bool,
) -> tuple[dict, str]:
    """Execute transcript enhancement pipeline (preprocess, diarize).

    Processes transcripts through optional enhancement steps, updating the
    latest transcript and its name as each step completes.

    Args:
        preprocess: Enable transcript preprocessing
        restore: Enable semantic restore in preprocessing
        diarize: Enable speaker diarization (includes word-level alignment)
        model: ASR model name (for file naming)
        latest: Latest transcript dict (input)
        latest_name: Latest transcript filename without extension (input)
        wd: Working directory Path
        progress: Progress tracker instance
        verbose: Enable verbose logging

    Returns:
        Tuple of (enhanced_transcript_dict, enhanced_transcript_name)
        - Returns input values unchanged if no enhancement steps enabled

    Resume Support:
        - Reuses existing aligned/diarized transcripts
        - Supports legacy filename formats
    """
    import json
    import time

    from .utils import build_preprocess_command, sanitize_model_name

    # 4) PREPROCESS (optional)
    if preprocess:
        progress.start_step("Preprocessing transcript (merge/normalize)")
        step_start = time.time()

        # Preprocess the latest transcript
        used_model = (latest or {}).get("asr_model", model) if isinstance(latest, dict) else model
        pre_file = wd / f"transcript-preprocessed-{sanitize_model_name(used_model)}.json"
        latest = _run(
            build_preprocess_command(pre_file, restore),
            stdin_payload=latest,  # latest contains the base transcript JSON
            verbose=verbose,
            save_to=pre_file,
            label=None,
        )
        latest_name = f"transcript-preprocessed-{used_model}"

        step_duration = time.time() - step_start
        progress.complete_step("Preprocessing completed", step_duration)

    # 5) DIARIZE (optional)
    if diarize:
        # Get model from latest transcript
        used_model = latest.get("asr_model", model)
        diarized_file = wd / f"transcript-diarized-{sanitize_model_name(used_model)}.json"

        # Check if already exists (also check legacy filenames)
        legacy_diarized_new = wd / f"diarized-transcript-{used_model}.json"
        legacy_diarized = wd / "diarized-transcript.json"
        if diarized_file.exists():
            logger.info(
                f"Found existing diarized transcript ({used_model}), skipping diarization"
            )
            diar = json.loads(diarized_file.read_text())
            progress.complete_step(
                f"Using existing diarized transcript ({used_model})", 0
            )
            latest = diar
            latest_name = f"transcript-diarized-{used_model}"
        elif legacy_diarized_new.exists():
            logger.info(f"Found existing legacy diarized transcript ({used_model}), using it")
            diar = json.loads(legacy_diarized_new.read_text())
            progress.complete_step("Using existing diarized transcript", 0)
            latest = diar
            latest_name = f"transcript-diarized-{used_model}"
        elif legacy_diarized.exists():
            logger.info("Found existing legacy diarized transcript, using it")
            diar = json.loads(legacy_diarized.read_text())
            progress.complete_step("Using existing diarized transcript", 0)
            latest = diar
            latest_name = "transcript-diarized"
        else:
            progress.start_step("Identifying speakers")
            step_start = time.time()
            # Debug: Check what we're passing to diarize
            if verbose:
                import click
                click.secho(
                    f"Debug: Passing {latest_name} JSON to diarize with {len(latest.get('segments', []))} segments",
                    fg="yellow",
                )
            from .services import CommandBuilder

            diarize_cmd = CommandBuilder("podx-diarize")  # Audio path comes from aligned transcript JSON
            diar = _run(
                diarize_cmd.build(),
                stdin_payload=latest,
                verbose=verbose,
                save_to=diarized_file,
                label=None,  # Progress handles the display
            )
            step_duration = time.time() - step_start
            progress.complete_step("Speaker diarization completed", step_duration)
            latest = diar
            latest_name = f"transcript-diarized-{used_model}"

    return latest, latest_name


def _execute_deepcast(
    deepcast: bool,
    model: str,
    deepcast_model: str,
    deepcast_temp: float,
    yaml_analysis_type: Optional[str],
    extract_markdown: bool,
    deepcast_pdf: bool,
    wd: Path,
    results: dict,
    progress,
    verbose: bool,
) -> None:
    """Execute deepcast analysis step.

    Handles AI-powered transcript analysis.

    Args:
        deepcast: Enable deepcast analysis
        model: ASR model name (for file naming)
        deepcast_model: AI model for deepcast analysis
        deepcast_temp: Temperature for deepcast LLM calls
        yaml_analysis_type: Optional analysis type from YAML config
        extract_markdown: Extract markdown from deepcast output
        deepcast_pdf: Generate PDF from deepcast output
        wd: Working directory Path
        results: Results dictionary (modified in place)
        progress: Progress tracker instance
        verbose: Enable verbose logging

    Side Effects:
        - Updates results dict with deepcast output paths
        - Creates deepcast JSON/MD files in working directory

    Resume Support:
        - Reuses existing deepcast analysis if available
    """
    import time

    from .utils import build_deepcast_command

    if not deepcast:
        return

    # Use model-specific filenames to allow multiple analyses
    model_suffix = deepcast_model.replace(".", "_").replace("-", "_")
    json_out = wd / f"deepcast-{model_suffix}.json"
    md_out = wd / f"deepcast-{model_suffix}.md"

    if json_out.exists():
        logger.info("Found existing deepcast analysis, skipping AI analysis")
        progress.complete_step("Using existing AI analysis", 0)
        results.update({"deepcast_json": str(json_out)})
        if extract_markdown and md_out.exists():
            results.update({"deepcast_md": str(md_out)})
    else:
        # Single-track deepcast always reads the latest processed transcript
        progress.start_step(f"Analyzing transcript with {deepcast_model}")
        step_start = time.time()
        latest_path = wd / "latest.json"
        meta_file = wd / "episode-meta.json"

        cmd = build_deepcast_command(
            input_path=latest_path,
            output_path=json_out,
            model=deepcast_model,
            temperature=deepcast_temp,
            meta_path=meta_file,
            analysis_type=yaml_analysis_type,
            extract_markdown=extract_markdown,
            generate_pdf=deepcast_pdf,
        )
        _run(cmd, verbose=verbose, save_to=None, label=None)
        step_duration = time.time() - step_start
        progress.complete_step("AI analysis completed", step_duration)
        results.update({"deepcast_json": str(json_out)})
        if extract_markdown and md_out.exists():
            results.update({"deepcast_md": str(md_out)})


def _execute_notion_upload(
    notion_db: str,
    wd: Path,
    results: dict,
    deepcast_model: str,
    model: str,
    podcast_prop: str,
    date_prop: str,
    episode_prop: str,
    model_prop: str,
    asr_prop: str,
    append_content: bool,
    progress,
    verbose: bool,
) -> None:
    """Execute Notion page creation/update with deepcast content.

    Uploads transcript analysis to Notion database, preferring exported markdown
    when available, falling back to model-specific deepcast files, and using
    JSON-only mode when no markdown exists.

    Args:
        notion_db: Notion database ID or key from YAML config
        wd: Working directory Path
        results: Results dictionary containing output file paths
        deepcast_model: AI model used for deepcast analysis
        model: ASR model name
        podcast_prop: Notion property name for podcast
        date_prop: Notion property name for date
        episode_prop: Notion property name for episode
        model_prop: Notion property name for model
        asr_prop: Notion property name for ASR provider
        append_content: Append to existing page instead of replacing
        progress: Progress tracker instance
        verbose: Enable verbose logging

    Side Effects:
        - Creates/updates Notion page
        - Saves notion.out.json to working directory
        - Updates results dict with notion output path
    """
    import time

    progress.start_step("Uploading to Notion")
    step_start = time.time()

    from .services import CommandBuilder

    # Prefer exported.md if available, else model-specific deepcast outputs, fallback to latest.txt
    model_suffix = deepcast_model.replace(".", "_").replace("-", "_")
    exported_md = Path(results.get("exported_md", "")) if results.get("exported_md") else None
    model_specific_md = wd / f"deepcast-{model_suffix}.md"
    model_specific_json = wd / f"deepcast-{model_suffix}.json"

    # Build command using CommandBuilder
    cmd = CommandBuilder("podx-notion")

    # If exported exists, use it directly
    if exported_md and exported_md.exists():
        md_path = str(exported_md)
        json_path = (
            str(model_specific_json) if model_specific_json.exists() else None
        )
        cmd.add_option("--markdown", md_path)
        cmd.add_option("--meta", str(wd / "episode-meta.json"))
        if json_path:
            cmd.add_option("--json", json_path)
    else:
        # Find any deepcast files if model-specific ones don't exist
        # Check for both new and legacy formats
        deepcast_files = list(wd.glob("deepcast-*.md"))
        fallback_md = deepcast_files[0] if deepcast_files else None

        # Prefer unified JSON mode if no separate markdown file exists
        if model_specific_json.exists() and not model_specific_md.exists():
            # Use unified JSON mode (deepcast JSON contains markdown)
            cmd.add_option("--input", str(model_specific_json))
        else:
            # Use separate markdown + JSON mode
            md_path = (
                str(model_specific_md)
                if model_specific_md.exists()
                else str(fallback_md) if fallback_md else str(wd / "latest.txt")
            )
            json_path = (
                str(model_specific_json) if model_specific_json.exists() else None
            )

            cmd.add_option("--markdown", md_path)
            cmd.add_option("--meta", str(wd / "episode-meta.json"))
            if json_path:
                cmd.add_option("--json", json_path)

    # Add common options
    cmd.add_option("--db", notion_db)
    cmd.add_option("--podcast-prop", podcast_prop)
    cmd.add_option("--date-prop", date_prop)
    cmd.add_option("--episode-prop", episode_prop)
    cmd.add_option("--model-prop", model_prop)
    cmd.add_option("--asr-prop", asr_prop)
    cmd.add_option("--deepcast-model", deepcast_model)
    cmd.add_option("--asr-model", model)  # The ASR model from transcription

    if append_content:
        cmd.add_flag("--append-content")
    # Default is replace, so no flag needed when append_content is False

    _ = _run(
        cmd.build(),
        verbose=verbose,
        save_to=wd / "notion.out.json",
        label=None,  # Progress handles the display
    )
    step_duration = time.time() - step_start
    progress.complete_step("Notion page created/updated", step_duration)
    results.update({"notion": str(wd / "notion.out.json")})


def _execute_cleanup(
    clean: bool,
    no_keep_audio: bool,
    wd: Path,
    latest_name: str,
    transcoded_path: Path,
    original_audio_path: Path | None,
    progress,
) -> None:
    """Execute optional file cleanup after pipeline completion.

    Removes intermediate transcript files and optionally audio files,
    while preserving final artifacts like latest.json, exported files,
    and deepcast outputs.

    Args:
        clean: Enable cleanup of intermediate files
        no_keep_audio: Also remove audio files
        wd: Working directory Path
        latest_name: Name of the latest transcript (without extension)
        transcoded_path: Path to transcoded audio file
        original_audio_path: Path to original audio file (may be None)
        progress: Progress tracker instance

    Side Effects:
        - Deletes intermediate transcript JSON files
        - Optionally deletes audio files
        - Logs cleanup actions
    """
    import time

    if not clean:
        return

    progress.start_step("Cleaning up intermediate files")
    step_start = time.time()

    # Keep final artifacts (small pointers)
    keep = {
        wd / "latest.json",
        wd / f"{latest_name}.txt",
        wd / f"{latest_name}.srt",
        wd / "notion.out.json",
        wd / "episode-meta.json",
        wd / "audio-meta.json",
    }
    # Keep all deepcast files (both new and legacy formats)
    keep.update(wd.glob("deepcast-*.json"))
    keep.update(wd.glob("deepcast-*.md"))

    cleaned_files = 0

    # Remove intermediate JSON files (both legacy and model-specific)
    cleanup_patterns = [
        "transcript.json",
        "transcript-*.json",
        # Legacy align/diarize formats (old)
        "aligned-transcript.json",
        "aligned-transcript-*.json",
        "diarized-transcript.json",
        "diarized-transcript-*.json",
        # New align/diarize formats
        "transcript-aligned.json",
        "transcript-aligned-*.json",
        "transcript-diarized.json",
        "transcript-diarized-*.json",
    ]
    for pattern in cleanup_patterns:
        for p in wd.glob(pattern):
            if p.exists() and p not in keep:
                try:
                    p.unlink()
                    cleaned_files += 1
                    logger.debug("Cleaned intermediate file", file=str(p))
                except Exception as e:
                    logger.warning(
                        "Failed to clean file", file=str(p), error=str(e)
                    )

    # Remove audio files if not keeping them
    if no_keep_audio:
        for p in [transcoded_path, original_audio_path]:
            if p and p.exists():
                try:
                    p.unlink()
                    cleaned_files += 1
                    logger.debug("Cleaned audio file", file=str(p))
                except Exception as e:
                    logger.warning(
                        "Failed to clean audio file", file=str(p), error=str(e)
                    )

    step_duration = time.time() - step_start
    progress.complete_step(
        f"Cleanup completed ({cleaned_files} files removed)", step_duration
    )


def _print_results_summary(
    start_time: float,
    steps: list[str],
    wd: Path,
    results: dict,
) -> None:
    """Print final pipeline summary with key results and JSON output.

    Displays completion message with total duration, key output files,
    and JSON results for programmatic use.

    Args:
        start_time: Pipeline start timestamp
        steps: List of pipeline steps that were executed
        wd: Working directory Path
        results: Results dictionary with output file paths

    Side Effects:
        - Logs completion info
        - Prints success message with duration
        - Prints key file paths with emojis
        - Prints full results as JSON
    """
    import json
    import time

    from .progress import format_duration, print_podx_info, print_podx_success

    # Final summary
    total_time = time.time() - start_time
    logger.info(
        "Pipeline completed",
        total_duration=total_time,
        steps_completed=len(steps),
        workdir=str(wd),
    )

    print_podx_success(f"Pipeline completed in {format_duration(total_time)}")

    # Show key results
    key_files = []
    if "latest_txt" in results:
        key_files.append(f"📄 Transcript: {results['latest_txt']}")
    if "latest_srt" in results:
        key_files.append(f"📺 Subtitles: {results['latest_srt']}")
    if "deepcast_md" in results:
        key_files.append(f"🤖 Analysis: {results['deepcast_md']}")
    if "notion" in results:
        key_files.append(f"☁️ Notion: {results['notion']}")

    if key_files:
        print_podx_info("\n".join(key_files))

    # Still print JSON for programmatic use
    print(json.dumps(results, indent=JSON_INDENT))


def _display_pipeline_config(
    diarize: bool,
    deepcast: bool,
    notion: bool,
    show: str | None,
    rss_url: str | None,
    date: str | None,
    model: str,
    compute: str,
) -> list[str]:
    """Display pipeline configuration and return list of steps.

    Builds the list of pipeline steps based on enabled features, logs the
    configuration, and displays it to the user.

    Args:
        diarize: Whether diarization is enabled (includes word-level alignment)
        deepcast: Whether deepcast analysis is enabled
        notion: Whether Notion upload is enabled
        show: Podcast show name
        rss_url: RSS feed URL
        date: Episode date filter
        model: ASR model name
        compute: Compute type

    Returns:
        List of pipeline step names
    """
    from .progress import print_podx_info

    steps = ["fetch", "transcode", "transcribe"]
    if diarize:
        steps.append("diarize")
    if deepcast:
        steps.append("deepcast")
    if notion:
        steps.append("notion")

    logger.info(
        "Starting pipeline",
        steps=steps,
        show=show,
        rss_url=rss_url,
        date=date,
        model=model,
        compute=compute,
    )

    print_podx_info(f"Pipeline: {' → '.join(steps)}")

    return steps


def _execute_export_formats(
    latest: dict,
    latest_name: str,
    wd: Path,
    progress,
    verbose: bool,
) -> dict:
    """Execute transcript export to TXT/SRT formats and build results dictionary.

    Exports the latest transcript to text and subtitle formats, then constructs
    the results dictionary with paths to all generated files.

    Args:
        latest: Latest transcript dictionary
        latest_name: Name of the latest transcript file (without extension)
        wd: Working directory path
        progress: Progress tracker
        verbose: Enable verbose logging

    Returns:
        Dictionary with paths to generated files (meta, audio, transcript, txt, srt)
    """
    import time
    from .services import CommandBuilder

    # Export to TXT/SRT formats
    progress.start_step("Exporting transcript files")
    step_start = time.time()

    export_cmd = (
        CommandBuilder("podx-export")
        .add_option("--formats", "txt,srt")
        .add_option("--output-dir", str(wd))
        .add_option("--input", str(wd / f"{latest_name}.json"))
        .add_flag("--replace")
    )
    export_result = _run(
        export_cmd.build(),
        stdin_payload=latest,
        verbose=verbose,
        label=None,  # Progress handles the display
    )
    step_duration = time.time() - step_start
    progress.complete_step("Transcript files exported (TXT, SRT)", step_duration)

    # Build results using export output paths when available
    exported_files = (
        export_result.get("files", {}) if isinstance(export_result, dict) else {}
    )
    results = {
        "meta": str(wd / "episode-meta.json"),
        "audio": str(wd / "audio-meta.json"),
        "transcript": str(wd / f"{latest_name}.json"),
        "latest_json": str(wd / "latest.json"),
    }
    if "txt" in exported_files:
        results["latest_txt"] = exported_files["txt"]
    else:
        results["latest_txt"] = str(wd / f"{latest_name}.txt")
    if "srt" in exported_files:
        results["latest_srt"] = exported_files["srt"]
    else:
        results["latest_srt"] = str(wd / f"{latest_name}.srt")

    return results


def _execute_export_final(
    preset: str | None,
    deepcast_pdf: bool,
    wd: Path,
    results: dict,
) -> None:
    """Execute final export of deepcast analysis to markdown/PDF.

    Exports deepcast output to timestamped markdown and optionally PDF files.

    Args:
        preset: ASR preset used (for track naming)
        deepcast_pdf: Generate PDF output
        wd: Working directory Path
        results: Results dictionary (modified in place with exported paths)

    Side Effects:
        - Exports markdown to wd/exported-<timestamp>.md
        - Optionally exports PDF to wd/exported-<timestamp>.pdf
        - Updates results dict with exported_md and exported_pdf keys
    """
    import json

    from .export import export_from_deepcast_json

    # Final export step (write exported-<timestamp>.* from deepcast output)
    try:
        single = results.get("deepcast_json")
        if single and Path(single).exists():
            export_source_path = Path(single)
            export_track = (preset or "balanced") if preset else "single"

            data = json.loads(export_source_path.read_text(encoding=DEFAULT_ENCODING))
            # Use unified exporter (handles deepcast JSON, and PDF auto-install)
            try:
                md_path, pdf_path = export_from_deepcast_json(data, wd, deepcast_pdf, track_hint=export_track)
                results["exported_md"] = str(md_path)
                if pdf_path is not None:
                    results["exported_pdf"] = str(pdf_path)
            except Exception:
                pass
    except Exception:
        pass


def _build_episode_metadata_display(
    selected: Dict[str, Any], meta: Dict[str, Any], config: Dict[str, Any]
) -> str:
    """Build episode metadata display for preview panel.

    Args:
        selected: Selected episode dictionary from scan
        meta: Episode metadata from episode-meta.json
        config: Pipeline configuration (for cost estimation)

    Returns:
        Formatted metadata string
    """
    from .utils.file_utils import format_duration

    # Basic metadata
    show = selected.get("show", "Unknown")
    date = selected.get("date", "Unknown")
    title = selected.get("title", "Unknown")

    # Get duration from transcript if available
    duration_seconds = None
    sel_dir = selected.get("directory")
    transcript_json = None
    if sel_dir:
        latest_path = sel_dir / "latest.json"
        if latest_path.exists():
            try:
                import json
                transcript_json = json.loads(latest_path.read_text(encoding=DEFAULT_ENCODING))
                segments = transcript_json.get("segments", [])
                if segments:
                    duration_seconds = int(max(s.get("end", 0) for s in segments))
            except Exception:
                pass

    # If no transcript, try to get from audio file using ffprobe
    if duration_seconds is None and sel_dir:
        audio_path = meta.get("audio_path")
        if audio_path and Path(audio_path).exists():
            try:
                import subprocess
                result = subprocess.run(
                    ["ffprobe", "-v", "error", "-show_entries", "format=duration",
                     "-of", "default=noprint_wrappers=1:nokey=1", audio_path],
                    capture_output=True, text=True, timeout=5
                )
                if result.returncode == 0:
                    duration_seconds = int(float(result.stdout.strip()))
            except Exception:
                pass

    duration_str = format_duration(duration_seconds)

    # Processing status
    num_transcripts = len(selected.get("transcripts", []))
    num_aligned = len(selected.get("aligned", []))
    num_diarized = len(selected.get("diarized", []))
    num_deepcasts = len(selected.get("deepcasts", []))
    has_consensus = selected.get("has_consensus", False)
    last_run = selected.get("last_run", "Never")

    # Build processing summary
    processing_parts = []
    if num_transcripts > 0:
        processing_parts.append(f"{num_transcripts} transcript{'s' if num_transcripts > 1 else ''}")
    if num_aligned > 0:
        processing_parts.append(f"{num_aligned} aligned")
    if num_diarized > 0:
        processing_parts.append(f"{num_diarized} diarized")
    if num_deepcasts > 0:
        processing_parts.append(f"{num_deepcasts} deepcast{'s' if num_deepcasts > 1 else ''}")
    if has_consensus:
        processing_parts.append("consensus")

    if processing_parts:
        processing_status = f"Existing: {', '.join(processing_parts)}"
        processing_status += f"\nLast run: {last_run}"
    else:
        processing_status = "No existing processed versions"

    # Cost estimate (if deepcast enabled and transcript available)
    cost_str = ""
    if config.get("deepcast") and transcript_json:
        try:
            from .deepcast import estimate_deepcast_cost
            from .model_catalog import load_model_catalog

            provider = (
                "openai"
                if config["deepcast_model"].startswith(OPENAI_MODEL_PREFIX) or "-" in config["deepcast_model"]
                else "anthropic"
            )
            catalog = load_model_catalog(refresh=False)
            est = estimate_deepcast_cost(
                transcript_json, provider, config["deepcast_model"], catalog
            )
            cost_str = f"\nEstimated cost: ${est.total_usd:.2f} (in≈{est.input_tokens:,} tok, out≈{est.output_tokens:,} tok)"
        except Exception:
            pass

    # Build final display
    metadata = (
        f"Show: {show}\n"
        f"Title: {title}\n"
        f"Released: {date}\n"
        f"Duration: {duration_str}"
        f"{cost_str}\n"
        f"\n{processing_status}"
    )

    return metadata


def _handle_interactive_mode(config: Dict[str, Any], scan_dir: Path, console: Any) -> tuple[Dict[str, Any], Path]:
    """Handle interactive episode selection and configuration.

    Displays rich table UI for episode selection and interactive
    configuration panel. Modifies config dict in place.

    Args:
        config: Pipeline configuration dictionary (modified in place)
        scan_dir: Directory to scan for episodes
        console: Rich console instance

    Returns:
        Tuple of (episode_metadata, working_directory)

    Raises:
        SystemExit: If user cancels selection
    """
    from .ui import select_episode_with_tui
    from rich.panel import Panel

    # 1. Episode selection
    selected, meta = select_episode_with_tui(
        scan_dir=scan_dir,
        show_filter=config["show"],
    )

    # 2. Interactive configuration panel
    from .ui import configure_pipeline_interactive

    updated_config = configure_pipeline_interactive(config)
    if updated_config is None:
        console.print("[dim]Cancelled[/dim]")
        raise SystemExit(0)

    # Merge updated config back
    config.update(updated_config)
    chosen_type = config.get("yaml_analysis_type")

    # 6. Episode metadata display
    episode_metadata = _build_episode_metadata_display(selected, meta, config)
    console.print(Panel(episode_metadata, title="Episode", border_style="cyan"))

    # 7. Pipeline preview
    stages = ["fetch", "transcode", "transcribe"]
    if config["diarize"]:
        stages.append("diarize")
    if config["preprocess"]:
        stages.append("preprocess" + ("+restore" if config["restore"] else ""))
    if config["deepcast"]:
        stages.append("deepcast")

    outputs = []
    if config["extract_markdown"]:
        outputs.append("markdown")
    if config["deepcast_pdf"]:
        outputs.append("pdf")

    def yn(val: bool) -> str:
        return "yes" if val else "no"

    preview = (
        f"Pipeline: {' → '.join(stages)}\n"
        f"ASR={config['model']} "
        f"diarize={yn(config['diarize'])} "
        f"preprocess={yn(config['preprocess'])} restore={yn(config['restore'])}\n"
        f"AI={config['deepcast_model']} type={chosen_type or '-'} outputs={','.join(outputs) or '-'}"
    )

    console.print(Panel(preview, title="Pipeline", border_style="green"))

    # 7. Final confirmation (strict y/n validation)
    while True:
        cont = input("Proceed? (y/n; q cancel) [Y]: ").strip()
        if not cont:
            break
        c = cont.lower()
        if c in {"q", "quit", "exit"}:
            console.print("[dim]Cancelled[/dim]")
            raise SystemExit(0)
        if c in {"y", "n"}:
            if c == "n":
                console.print("[dim]Cancelled[/dim]")
                raise SystemExit(0)
            break
        print("Please enter 'y' or 'n' (or 'q' to cancel).")

    # Update config with chosen analysis type
    config["yaml_analysis_type"] = chosen_type

    # Return metadata and working directory
    workdir = selected["directory"]
    return meta, workdir


@main.command("run", help="Orchestrate the complete podcast processing pipeline.")
@click.option("--show", help="Podcast show name (iTunes search)")
@click.option("--rss-url", help="Direct RSS feed URL (alternative to --show)")
@click.option(
    "--youtube-url", help="YouTube video URL (alternative to --show and --rss-url)"
)
@click.option("--date", help="Episode date (YYYY-MM-DD)")
@click.option("--title-contains", help="Substring to match in episode title")
@click.option(
    "--workdir",
    type=click.Path(path_type=Path),
    help="Override working directory (bypasses smart naming)",
)
@click.option(
    "--fmt",
    default="wav16",
    type=click.Choice(["wav16", "mp3", "aac"]),
    help="Transcode format for ASR step [default: wav16]",
)
@click.option(
    "--model",
    default=lambda: get_config().default_asr_model,
    help="ASR transcription model",
)
@click.option(
    "--asr-provider",
    type=click.Choice(["auto", "local", "openai", "hf"]),
    default="auto",
    help="ASR provider (auto-detect by model prefix/alias if 'auto')",
)
@click.option(
    "--compute",
    default=lambda: get_config().default_compute,
    type=click.Choice(["int8", "int8_float16", "float16", "float32"]),
    help="Compute type",
)
@click.option(
    "--preprocess/--no-preprocess",
    default=True,
    help="Run preprocessing (merge/normalize) before diarization/deepcast (default: enabled)",
)
@click.option(
    "--restore/--no-restore",
    default=False,
    help="When preprocessing, attempt semantic restore using an LLM",
)
@click.option(
    "--diarize/--no-diarize",
    default=True,
    help="Run diarization (default: enabled; use --no-diarize to skip)",
)
@click.option(
    "--deepcast/--no-deepcast",
    default=True,
    help="Run LLM summarization (default: enabled; use --no-deepcast to skip)",
)
@click.option(
    "--interactive",
    "interactive_select",
    is_flag=True,
    help="Browse existing episodes and select one to process",
)
@click.option(
    "--scan-dir",
    type=click.Path(exists=True, path_type=Path),
    default=".",
    help="Directory to scan for episodes when using --interactive",
)
@click.option(
    "--fetch-new",
    is_flag=True,
    help="When used with --interactive and --show, open fetch browser to add new episodes before selection",
)
@click.option(
    "--deepcast-model",
    default=lambda: get_config().openai_model,
    help="OpenAI model for AI analysis",
)
@click.option(
    "--deepcast-temp",
    default=lambda: get_config().openai_temperature,
    type=float,
    help="OpenAI temperature for deepcast",
)
@click.option(
    "--extract-markdown/--no-markdown",
    "extract_markdown",
    default=True,
    help="Extract markdown file when running deepcast (default: enabled)",
)
@click.option(
    "--deepcast-pdf",
    "deepcast_pdf",
    is_flag=True,
    help="Also render a PDF of the deepcast markdown (requires pandoc)",
)
@click.option(
    "--notion",
    is_flag=True,
    help="Upload to Notion database (default: no upload)",
)
@click.option(
    "--db",
    "notion_db",
    default=lambda: get_config().notion_db_id,
    help="Notion database ID (required if --notion)",
)
@click.option(
    "--podcast-prop",
    default=lambda: get_config().notion_podcast_prop,
    help="Notion property name for podcast name",
)
@click.option(
    "--date-prop",
    default=lambda: get_config().notion_date_prop,
    help="Notion property name for date",
)
@click.option(
    "--episode-prop",
    default=lambda: get_config().notion_episode_prop,
    help="Notion property name for episode title",
)
@click.option(
    "--model-prop",
    default="Model",
    help="Notion property name for deepcast model",
)
@click.option(
    "--asr-prop",
    default="ASR Model",
    help="Notion property name for ASR model",
)
@click.option(
    "--append-content",
    is_flag=True,
    help="Append to page body in Notion instead of replacing (default: replace)",
)
@click.option(
    "--full",
    is_flag=True,
    help="Enable full pipeline: --deepcast --extract-markdown --notion (convenience flag)",
)
@click.option("-v", "--verbose", is_flag=True, help="Print interstitial outputs")
@click.option(
    "--clean",
    is_flag=True,
    help="Delete intermediates after success (default: keep all files)",
)
@click.option(
    "--no-keep-audio",
    is_flag=True,
    help="Delete audio files when --clean is used (default: keep audio)",
)
def run(
    show: Optional[str],
    rss_url: Optional[str],
    youtube_url: Optional[str],
    date: Optional[str],
    title_contains: Optional[str],
    workdir: Optional[Path],
    fmt: str,
    model: str,
    compute: str,
    asr_provider: str,
    preprocess: bool,
    restore: bool,
    diarize: bool,
    deepcast: bool,
    interactive_select: bool,
    scan_dir: Path,
    fetch_new: bool,
    deepcast_model: str,
    deepcast_temp: float,
    extract_markdown: bool,
    deepcast_pdf: bool,
    notion: bool,
    notion_db: Optional[str],
    podcast_prop: str,
    date_prop: str,
    episode_prop: str,
    model_prop: str,
    asr_prop: str,
    append_content: bool,
    full: bool,
    verbose: bool,
    clean: bool,
    no_keep_audio: bool,
):
    """Orchestrate the complete podcast processing pipeline.

    This function handles the end-to-end workflow from episode fetch to publication,
    supporting various pipeline configurations and resume capabilities.

    Pipeline Flow (v2.0 - simplified):
        1. Source Selection: Fetch from RSS, YouTube, or interactive browser
        2. Audio Processing: Transcode to target format
        3. Transcription: ASR transcription
        4. Enhancement: Diarization (with internal alignment), preprocessing
        5. Analysis: AI-powered deepcast with configurable types (default: ON)
        6. Export: Markdown extraction (default: ON)
        7. Publication: Optional Notion upload

    v2.0 Defaults (enabled by default):
        - Diarization, Preprocessing, Deepcast, Markdown extraction
        - Use --no-diarize, --no-preprocess, --no-deepcast, --no-markdown to disable

    Resume Support:
        The function detects existing artifacts and offers to skip completed steps,
        maintaining state in run-state.json for crash recovery.

    Args:
        show: Podcast name for iTunes search (alternative to rss_url/youtube_url)
        rss_url: Direct RSS feed URL
        youtube_url: YouTube video/channel URL
        date: Filter episode by date (YYYY-MM-DD or partial)
        title_contains: Filter episode by title substring
        workdir: Working directory path (auto-generated if not specified)
        fmt: Output audio format (wav16/mp3/aac)
        model: ASR transcription model
        compute: ASR compute type (int8/float16/float32)
        asr_provider: ASR provider (auto/local/openai/hf)
        preset: ASR preset (balanced/precision/recall)
        align: Enable word-level alignment (WhisperX)
        preprocess: Enable transcript preprocessing
        restore: Enable semantic restore (LLM-based)
        diarize: Enable speaker diarization (WhisperX)
        deepcast: Enable AI analysis
        interactive_select: Use interactive episode selection UI
        scan_dir: Directory to scan for episodes in interactive mode
        fetch_new: Force fetch new episode (skip interactive selection)
        deepcast_model: AI model for deepcast analysis
        deepcast_temp: Temperature for deepcast LLM calls
        extract_markdown: Extract markdown from deepcast output
        deepcast_pdf: Generate PDF from deepcast output
        notion: Upload to Notion
        notion_db: Notion database key (from YAML config)
        podcast_prop: Notion property name for podcast
        date_prop: Notion property name for date
        episode_prop: Notion property name for episode
        model_prop: Notion property name for model
        asr_prop: Notion property name for ASR provider
        append_content: Append to existing Notion page instead of replacing
        full: Convenience flag to enable align + deepcast + markdown + notion
        verbose: Enable verbose logging
        clean: Clean intermediate files after completion
        no_keep_audio: Don't keep audio files after transcription

    Raises:
        ValidationError: On configuration or input validation failures
        SystemExit: On user cancellation or missing required configuration

    Returns:
        Exits with status code 0 on success, non-zero on failure
    """
    # 1. Build pipeline configuration from CLI args with preset transformations
    config = _build_pipeline_config(
        show=show,
        rss_url=rss_url,
        youtube_url=youtube_url,
        date=date,
        title_contains=title_contains,
        workdir=workdir,
        fmt=fmt,
        model=model,
        compute=compute,
        asr_provider=asr_provider,
        preprocess=preprocess,
        restore=restore,
        diarize=diarize,
        deepcast=deepcast,
        deepcast_model=deepcast_model,
        deepcast_temp=deepcast_temp,
        extract_markdown=extract_markdown,
        deepcast_pdf=deepcast_pdf,
        notion=notion,
        notion_db=notion_db,
        podcast_prop=podcast_prop,
        date_prop=date_prop,
        episode_prop=episode_prop,
        model_prop=model_prop,
        asr_prop=asr_prop,
        append_content=append_content,
        full=full,
        verbose=verbose,
        clean=clean,
        no_keep_audio=no_keep_audio,
    )

    # Print header and start progress tracking
    print_podx_header()

    start_time = time.time()

    # Initialize results dictionary
    results = {}

    # Use progress tracking for the entire pipeline
    with PodxProgress() as progress:
        # We'll determine the actual workdir after fetching metadata
        wd = None  # Will be set after fetch

        # 2. Interactive selection: choose existing episode and configure pipeline
        interactive_meta = None
        interactive_wd = None
        if interactive_select:
            from .ui import make_console

            console = make_console()
            interactive_meta, interactive_wd = _handle_interactive_mode(config, scan_dir, console)

        # 3. Fetch episode metadata and determine working directory
        meta, wd = _execute_fetch(
            config=config,
            interactive_mode_meta=interactive_meta,
            interactive_mode_wd=interactive_wd,
            progress=progress,
            verbose=config["verbose"],
        )

        # Show pipeline configuration (after YAML/JSON config is applied)
        steps = _display_pipeline_config(
            diarize=config["diarize"],
            deepcast=config["deepcast"],
            notion=config["notion"],
            show=config["show"],
            rss_url=config["rss_url"],
            date=config["date"],
            model=config["model"],
            compute=config["compute"],
        )

        # Working directory determined by _execute_fetch()
        wd.mkdir(parents=True, exist_ok=True)

        # For YouTube URLs, now do the full fetch with proper workdir
        if config["youtube_url"]:
            from .youtube import fetch_youtube_episode

            progress.start_step("Downloading YouTube audio")
            meta = fetch_youtube_episode(config["youtube_url"], wd)
            progress.complete_step(f"YouTube audio downloaded: {wd / '*.mp3'}")
        # Save metadata to the determined workdir
        (wd / "episode-meta.json").write_text(json.dumps(meta, indent=2))

        # Track original audio path for cleanup
        original_audio_path = Path(meta["audio_path"]) if "audio_path" in meta else None

        # 2) TRANSCODE → audio-meta.json
        audio_meta_file = wd / "audio-meta.json"
        if audio_meta_file.exists():
            logger.info("Found existing audio metadata, skipping transcode")
            audio = json.loads(audio_meta_file.read_text())
            progress.complete_step(f"Using existing {config['fmt']} audio", 0)
        else:
            progress.start_step(f"Transcoding audio to {config['fmt']}")
            step_start = time.time()
            from .services import CommandBuilder

            # Convert fmt enum to string value if needed
            fmt_value = config["fmt"].value if hasattr(config["fmt"], 'value') else config["fmt"]

            transcode_cmd = (
                CommandBuilder("podx-transcode")
                .add_option("--to", fmt_value)
                .add_option("--outdir", str(wd))
            )
            audio = _run(
                transcode_cmd.build(),
                stdin_payload=meta,
                verbose=config["verbose"],
                save_to=audio_meta_file,
                label=None,  # Progress handles the display
            )
            step_duration = time.time() - step_start
            progress.complete_step(f"Audio transcoded to {config['fmt']}", step_duration)

        # Track transcoded audio path for cleanup
        transcoded_path = Path(audio["audio_path"])

        # 3) TRANSCRIBE → transcript-{model}.json
        latest, latest_name = _execute_transcribe(
            model=config["model"],
            compute=config["compute"],
            asr_provider=config["asr_provider"],
            audio=audio,
            wd=wd,
            progress=progress,
            verbose=config["verbose"],
        )

        # 4-6) ENHANCEMENT PIPELINE (preprocess, align, diarize)
        latest, latest_name = _execute_enhancement(
            preprocess=config["preprocess"],
            restore=config["restore"],
            diarize=config["diarize"],
            model=config["model"],
            latest=latest,
            latest_name=latest_name,
            wd=wd,
            progress=progress,
            verbose=config["verbose"],
        )

        # Always keep a pointer to the latest JSON/SRT/TXT for convenience
        (wd / "latest.json").write_text(json.dumps(latest, indent=JSON_INDENT), encoding=DEFAULT_ENCODING)

        # Export to TXT/SRT formats and build results dictionary
        results = _execute_export_formats(
            latest=latest,
            latest_name=latest_name,
            wd=wd,
            progress=progress,
            verbose=config["verbose"],
        )

        # 7) DEEPCAST (optional)
        _execute_deepcast(
            deepcast=config["deepcast"],
            model=config["model"],
            deepcast_model=config["deepcast_model"],
            deepcast_temp=config["deepcast_temp"],
            yaml_analysis_type=config["yaml_analysis_type"],
            extract_markdown=config["extract_markdown"],
            deepcast_pdf=config["deepcast_pdf"],
            wd=wd,
            results=results,
            progress=progress,
            verbose=config["verbose"],
        )

        # Final export step (write exported-<timestamp>.* from deepcast)
        _execute_export_final(
            preset=config["preset"],
            deepcast_pdf=config["deepcast_pdf"],
            wd=wd,
            results=results,
        )

        # 7) NOTION (optional) — requires DB id
        if config["notion"]:
            if not config["notion_db"]:
                raise SystemExit(
                    "Please pass --db or set NOTION_DB_ID environment variable"
                )

            _execute_notion_upload(
                notion_db=config["notion_db"],
                wd=wd,
                results=results,
                deepcast_model=config["deepcast_model"],
                model=config["model"],
                podcast_prop=config["podcast_prop"],
                date_prop=config["date_prop"],
                episode_prop=config["episode_prop"],
                model_prop=config["model_prop"],
                asr_prop=config["asr_prop"],
                append_content=config["append_content"],
                progress=progress,
                verbose=config["verbose"],
            )

        # 8) Optional cleanup
        _execute_cleanup(
            clean=config["clean"],
            no_keep_audio=config["no_keep_audio"],
            wd=wd,
            latest_name=latest_name,
            transcoded_path=transcoded_path,
            original_audio_path=original_audio_path,
            progress=progress,
        )

    # Final summary
    _print_results_summary(
        start_time=start_time,
        steps=steps,
        wd=wd,
        results=results,
    )


# Add individual commands as subcommands to main CLI group
# This provides a consistent interface: podx <command> instead of podx-<command>


## Deprecated: info command has been removed in favor of 'podx list'


@main.command("fetch")
@click.pass_context
def fetch_cmd(ctx):
    """Find and download podcast episodes by show name or RSS URL."""
    # Pass through to the original fetch.main() with sys.argv adjustments
    import sys

    # Remove 'podx fetch' from sys.argv and call fetch.main()
    original_argv = sys.argv.copy()
    sys.argv = ["podx-fetch"] + sys.argv[2:]  # Keep original args after 'fetch'
    try:
        fetch.main()
    finally:
        sys.argv = original_argv


@main.command("transcode")
@click.pass_context
def transcode_cmd(ctx):
    """Convert audio files to different formats (wav16, mp3, aac)."""
    import sys

    original_argv = sys.argv.copy()
    sys.argv = ["podx-transcode"] + sys.argv[2:]
    try:
        transcode.main()
    finally:
        sys.argv = original_argv


@main.command("transcribe")
@click.pass_context
def transcribe_cmd(ctx):
    """Convert audio to text using Whisper ASR models."""
    import sys

    original_argv = sys.argv.copy()
    sys.argv = ["podx-transcribe"] + sys.argv[2:]
    try:
        transcribe.main()
    finally:
        sys.argv = original_argv


@main.command("diarize")
@click.pass_context
def diarize_cmd(ctx):
    """Add speaker identification to transcripts using WhisperX."""
    import sys

    original_argv = sys.argv.copy()
    sys.argv = ["podx-diarize"] + sys.argv[2:]
    try:
        diarize.main()
    finally:
        sys.argv = original_argv


@main.command("export")
@click.pass_context
def export_cmd(ctx):
    """Export transcripts to various formats (TXT, SRT, VTT, MD)."""
    import sys

    original_argv = sys.argv.copy()
    sys.argv = ["podx-export"] + sys.argv[2:]
    try:
        export.main()
    finally:
        sys.argv = original_argv


@main.command("deepcast")
@click.pass_context
def deepcast_cmd(ctx):
    """AI-powered transcript analysis and summarization."""
    import sys

    original_argv = sys.argv.copy()
    sys.argv = ["podx-deepcast"] + sys.argv[2:]
    try:
        deepcast.main()
    finally:
        sys.argv = original_argv


@main.command("models")
@click.pass_context
def models_cmd(ctx):
    """List AI models with pricing and estimate deepcast cost."""
    import sys

    original_argv = sys.argv.copy()
    sys.argv = ["podx-models"] + sys.argv[2:]
    try:
        from . import models as models_cli
        models_cli.main()
    finally:
        sys.argv = original_argv


@main.command("notion")
@click.pass_context
def notion_cmd(ctx):
    """Upload processed content to Notion databases."""
    import sys

    original_argv = sys.argv.copy()
    sys.argv = ["podx-notion"] + sys.argv[2:]
    try:
        notion.main()
    finally:
        sys.argv = original_argv


# Add convenience workflow commands
@main.command("quick", hidden=True)
@click.option("--show", help="Podcast show name (iTunes search)")
@click.option("--rss-url", help="Direct RSS feed URL (alternative to --show)")
@click.option(
    "--youtube-url", help="YouTube video URL (alternative to --show and --rss-url)"
)
@click.option("--date", help="Episode date (YYYY-MM-DD)")
@click.option("--title-contains", help="Substring to match in episode title")
@click.option(
    "--model", default=lambda: get_config().default_asr_model, help="ASR model"
)
@click.option(
    "--asr-provider",
    type=click.Choice(["auto", "local", "openai", "hf"]),
    default="auto",
    help="ASR provider for transcribe",
)
@click.option(
    "--compute",
    default=lambda: get_config().default_compute,
    type=click.Choice(["int8", "int8_float16", "float16", "float32"]),
    help="Compute type",
)
@click.option("-v", "--verbose", is_flag=True, help="Print interstitial outputs")
def quick(show, rss_url, youtube_url, date, title_contains, model, asr_provider, compute, verbose):
    """Quick workflow: fetch + transcribe only (fastest option)."""
    click.secho("[deprecated] Use: podx run (with no extra flags)", fg="yellow")
    click.echo("🚀 Running quick transcription workflow...")

    # Use the existing run command but with minimal options (all flags defaulted to False)
    ctx = click.get_current_context()
    ctx.invoke(
        run,
        show=show,
        rss_url=rss_url,
        youtube_url=youtube_url,
        date=date,
        title_contains=title_contains,
        model=model,
        compute=compute,
        asr_provider=asr_provider,
        align=False,
        diarize=False,
        deepcast=False,
        extract_markdown=False,
        notion=False,
        verbose=verbose,
        clean=False,
        model_prop="Model",
    )


@main.command("analyze", hidden=True)
@click.option("--show", help="Podcast show name (iTunes search)")
@click.option("--rss-url", help="Direct RSS feed URL (alternative to --show)")
@click.option(
    "--youtube-url", help="YouTube video URL (alternative to --show and --rss-url)"
)
@click.option("--date", help="Episode date (YYYY-MM-DD)")
@click.option("--title-contains", help="Substring to match in episode title")
@click.option(
    "--model", default=lambda: get_config().default_asr_model, help="ASR model"
)
@click.option(
    "--asr-provider",
    type=click.Choice(["auto", "local", "openai", "hf"]),
    default="auto",
    help="ASR provider for transcribe",
)
@click.option(
    "--compute",
    default=lambda: get_config().default_compute,
    type=click.Choice(["int8", "int8_float16", "float16", "float32"]),
    help="Compute type",
)
@click.option(
    "--deepcast-model",
    default=lambda: get_config().openai_model,
    help="AI analysis model",
)
@click.option(
    "--type",
    "podcast_type",
    type=click.Choice(
        [
            "interview",
            "tech",
            "business",
            "news",
            "educational",
            "narrative",
            "comedy",
            "general",
        ]
    ),
    help="Podcast type for specialized analysis",
)
@click.option("-v", "--verbose", is_flag=True, help="Print interstitial outputs")
def analyze(
    show,
    rss_url,
    youtube_url,
    date,
    title_contains,
    model,
    asr_provider,
    compute,
    deepcast_model,
    podcast_type,
    verbose,
):
    """Analysis workflow: transcribe + AI analysis (recommended)."""
    click.secho("[deprecated] Use: podx run (deepcast + markdown enabled by default in v2.0)", fg="yellow")
    click.echo("🤖 Running analysis workflow...")

    ctx = click.get_current_context()
    ctx.invoke(
        run,
        show=show,
        rss_url=rss_url,
        youtube_url=youtube_url,
        date=date,
        title_contains=title_contains,
        model=model,
        compute=compute,
        asr_provider=asr_provider,
        align=True,
        deepcast=True,
        extract_markdown=True,
        deepcast_model=deepcast_model,
        verbose=verbose,
        clean=False,
        model_prop="Model",
    )


@main.command("publish", hidden=True)
@click.option("--show", help="Podcast show name (iTunes search)")
@click.option("--rss-url", help="Direct RSS feed URL (alternative to --show)")
@click.option(
    "--youtube-url", help="YouTube video URL (alternative to --show and --rss-url)"
)
@click.option("--date", help="Episode date (YYYY-MM-DD)")
@click.option("--title-contains", help="Substring to match in episode title")
@click.option(
    "--db",
    "notion_db",
    default=lambda: get_config().notion_db_id,
    help="Notion database ID",
)
@click.option(
    "--deepcast-model",
    default=lambda: get_config().openai_model,
    help="AI analysis model",
)
@click.option(
    "--type",
    "podcast_type",
    type=click.Choice(
        [
            "interview",
            "tech",
            "business",
            "news",
            "educational",
            "narrative",
            "comedy",
            "general",
        ]
    ),
    help="Podcast type for specialized analysis",
)
@click.option("-v", "--verbose", is_flag=True, help="Print interstitial outputs")
def publish(
    show,
    rss_url,
    youtube_url,
    date,
    title_contains,
    notion_db,
    deepcast_model,
    podcast_type,
    verbose,
):
    """Publishing workflow: full pipeline + Notion upload (complete)."""
    click.secho("[deprecated] Use: podx run --notion (deepcast + markdown enabled by default in v2.0)", fg="yellow")
    click.echo("📝 Running publishing workflow...")

    ctx = click.get_current_context()
    # Equivalent to selecting the publish workflow
    ctx.invoke(
        run,
        show=show,
        rss_url=rss_url,
        youtube_url=youtube_url,
        date=date,
        title_contains=title_contains,
        notion_db=notion_db,
        deepcast_model=deepcast_model,
        align=True,
        deepcast=True,
        extract_markdown=True,
        notion=True,
        verbose=verbose,
        clean=False,
        model_prop="Model",
    )


# Add utility commands
@main.command("help")
@click.argument("topic", required=False)
@click.option("--examples", is_flag=True, help="Show usage examples")
@click.option("--pipeline", is_flag=True, help="Show pipeline flow diagram")
def help_command(topic, examples, pipeline):
    """Enhanced help system with examples and pipeline diagrams."""
    ctx = click.get_current_context()
    ctx.invoke(help_cmd, examples=examples, pipeline=pipeline)


@main.command("list", help="Shim: run podx-list with the given arguments")
@click.argument("args", nargs=-1)
def list_shim(args: tuple[str, ...]):
    import sys
    original_argv = sys.argv.copy()
    sys.argv = ["podx-list", *sys.argv[2:]]
    try:
        from .list import main as list_main
        list_main()
    finally:
        sys.argv = original_argv


@main.command("config")
@click.argument(
    "action",
    type=click.Choice(["show", "edit", "reset"]),
    required=False,
    default="show",
)
def config_command(action):
    """Configuration management for podx."""
    config = get_config()

    if action == "show":
        from rich.console import Console
        from rich.table import Table

        console = Console()
        table = Table(title="🔧 Podx Configuration")
        table.add_column("Setting", style="cyan")
        table.add_column("Value", style="green")
        table.add_column("Environment Variable", style="yellow")

        # Show key configuration values
        table.add_row("ASR Model", config.default_asr_model, "PODX_DEFAULT_MODEL")
        table.add_row("Compute Type", config.default_compute, "PODX_DEFAULT_COMPUTE")
        table.add_row("OpenAI Model", config.openai_model, "OPENAI_MODEL")
        table.add_row(
            "OpenAI Temperature", str(config.openai_temperature), "OPENAI_TEMPERATURE"
        )
        table.add_row("Log Level", config.log_level, "PODX_LOG_LEVEL")
        table.add_row("Log Format", config.log_format, "PODX_LOG_FORMAT")
        table.add_row("Max Retries", str(config.max_retries), "PODX_MAX_RETRIES")

        # Show API keys status (without revealing them)
        openai_status = "✅ Set" if config.openai_api_key else "❌ Not set"
        notion_status = "✅ Set" if config.notion_token else "❌ Not set"

        table.add_row("OpenAI API Key", openai_status, "OPENAI_API_KEY")
        table.add_row("Notion Token", notion_status, "NOTION_TOKEN")
        table.add_row(
            "Notion DB ID", config.notion_db_id or "❌ Not set", "NOTION_DB_ID"
        )

        console.print(table)

        console.print(
            "\n💡 [bold]Tip:[/bold] Set environment variables in your shell or .env file"
        )

    elif action == "edit":
        click.echo("📝 Opening configuration help...")
        click.echo("\nTo configure podx, set these environment variables:")
        click.echo("  export PODX_DEFAULT_MODEL=medium.en")
        click.echo("  export OPENAI_API_KEY=your_key_here")
        click.echo("  export NOTION_TOKEN=your_token_here")
        click.echo("  export NOTION_DB_ID=your_db_id_here")
        click.echo("\nOr create a .env file in your project directory.")

    elif action == "reset":
        from .config import reset_config

        reset_config()
        click.echo(
            "✅ Configuration cache reset. New values will be loaded on next run."
        )


@main.group("plugin")
def plugin_group():
    """Plugin management commands."""
    pass


# Lightweight shims to expose individual tools under the unified `podx` namespace
@main.command("preprocess", help="Shim: run podx-preprocess with the given arguments")
@click.argument("args", nargs=-1)
def preprocess_shim(args: tuple[str, ...]):
    code = _run_passthrough(["podx-preprocess", *args])
    sys.exit(code)


@main.command("agreement", help="Shim: run podx-agreement with the given arguments")
@click.argument("args", nargs=-1)
def agreement_shim(args: tuple[str, ...]):
    code = _run_passthrough(["podx-agreement", *args])
    sys.exit(code)


@main.command("consensus", help="Shim: run podx-consensus with the given arguments")
@click.argument("args", nargs=-1)
def consensus_shim(args: tuple[str, ...]):
    code = _run_passthrough(["podx-consensus", *args])
    sys.exit(code)


@plugin_group.command("list")
@click.option(
    "--type",
    "plugin_type",
    type=click.Choice([t.value for t in PluginType]),
    help="Filter by plugin type",
)
def list_plugins(plugin_type):
    """List available plugins."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    manager = PluginManager()

    # Auto-discover plugins
    manager.discover_plugins()

    # Filter by type if specified
    filter_type = None
    if plugin_type:
        filter_type = PluginType(plugin_type)

    plugins = manager.get_available_plugins(filter_type)

    if not plugins:
        console.print("No plugins found.")
        return

    table = Table(title="🔌 Available Plugins")
    table.add_column("Name", style="cyan", no_wrap=True)
    table.add_column("Type", style="magenta")
    table.add_column("Version", style="green")
    table.add_column("Description", style="white")
    table.add_column("Status", style="yellow")

    for name, metadata in plugins.items():
        status = "✅ Enabled" if metadata.enabled else "❌ Disabled"
        table.add_row(
            name,
            metadata.plugin_type.value,
            metadata.version,
            metadata.description,
            status,
        )

    console.print(table)

    # Show plugin type counts
    type_counts = {}
    for metadata in plugins.values():
        type_name = metadata.plugin_type.value
        type_counts[type_name] = type_counts.get(type_name, 0) + 1

    console.print(f"\n📊 Found {len(plugins)} plugins across {len(type_counts)} types")
    for plugin_type, count in sorted(type_counts.items()):
        console.print(f"  {plugin_type}: {count}")


@plugin_group.command("info")
@click.argument("plugin_name")
def plugin_info(plugin_name):
    """Show detailed information about a plugin."""
    from rich.console import Console
    from rich.panel import Panel
    from rich.table import Table

    console = Console()
    manager = PluginManager()
    manager.discover_plugins()

    registry = get_registry()
    plugin = registry.get_plugin(plugin_name)

    if not plugin:
        console.print(f"❌ Plugin '{plugin_name}' not found")
        return

    metadata = plugin.metadata

    # Create info panel
    info_text = f"""**Name:** {metadata.name}
**Version:** {metadata.version}
**Author:** {metadata.author}
**Type:** {metadata.plugin_type.value}
**Status:** {"✅ Enabled" if metadata.enabled else "❌ Disabled"}

**Description:**
{metadata.description}"""

    if metadata.dependencies:
        info_text += f"\n\n**Dependencies:**\n{', '.join(metadata.dependencies)}"

    console.print(Panel(info_text, title=f"🔌 Plugin: {plugin_name}"))

    # Show configuration schema if available
    if metadata.config_schema:
        table = Table(title="⚙️ Configuration Schema")
        table.add_column("Parameter", style="cyan")
        table.add_column("Type", style="magenta")
        table.add_column("Required", style="red")
        table.add_column("Default", style="green")

        for param, schema in metadata.config_schema.items():
            param_type = schema.get("type", "string")
            required = "Yes" if schema.get("required", False) else "No"
            default = str(schema.get("default", "N/A"))

            table.add_row(param, param_type, required, default)

        console.print(table)


@plugin_group.command("discover")
@click.option(
    "--dir",
    "plugin_dirs",
    multiple=True,
    help="Additional directories to scan for plugins",
)
def discover_plugins(plugin_dirs):
    """Discover and load plugins from directories."""
    from rich.console import Console

    console = Console()
    manager = PluginManager()

    # Convert string paths to Path objects
    extra_dirs = [Path(d) for d in plugin_dirs] if plugin_dirs else []

    console.print("🔍 Discovering plugins...")

    # Discover plugins
    if extra_dirs:
        manager.discover_plugins(extra_dirs)
    else:
        manager.discover_plugins()

    plugins = manager.get_available_plugins()

    console.print(f"✅ Discovered {len(plugins)} plugins")

    # Show summary by type
    type_counts = {}
    for metadata in plugins.values():
        type_name = metadata.plugin_type.value
        type_counts[type_name] = type_counts.get(type_name, 0) + 1

    for plugin_type, count in sorted(type_counts.items()):
        console.print(f"  {plugin_type}: {count} plugins")


@plugin_group.command("create")
@click.argument("plugin_name")
@click.argument("plugin_type", type=click.Choice([t.value for t in PluginType]))
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(path_type=Path),
    default=Path.cwd() / "plugins",
    help="Output directory for plugin template",
)
def create_plugin(plugin_name, plugin_type, output_dir):
    """Create a new plugin template."""
    from rich.console import Console

    from .plugins import create_plugin_template

    console = Console()

    # Ensure output directory exists
    output_dir.mkdir(parents=True, exist_ok=True)

    # Create plugin template
    plugin_type_enum = PluginType(plugin_type)
    plugin_file = create_plugin_template(plugin_type_enum, plugin_name, output_dir)

    console.print(f"✅ Plugin template created: {plugin_file}")
    console.print(f"📝 Edit the file to implement your {plugin_type} plugin")
    console.print(f"📚 See documentation for {plugin_type} plugin interface details")


@plugin_group.command("test")
@click.argument("plugin_name")
def test_plugin(plugin_name):
    """Test a plugin's basic functionality."""
    from rich.console import Console

    console = Console()
    manager = PluginManager()
    manager.discover_plugins()

    registry = get_registry()
    plugin = registry.get_plugin(plugin_name)

    if not plugin:
        console.print(f"❌ Plugin '{plugin_name}' not found")
        return

    console.print(f"🧪 Testing plugin: {plugin_name}")

    # Test configuration validation
    try:
        config = {}  # Empty config for basic test
        valid = plugin.validate_config(config)
        status = "✅ Passed" if valid else "❌ Failed"
        console.print(f"  Config validation: {status}")
    except Exception as e:
        console.print(f"  Config validation: ❌ Error - {e}")

    # Test initialization (if config validation passed)
    try:
        plugin.initialize({})
        console.print("  Initialization: ✅ Passed")
    except Exception as e:
        console.print(f"  Initialization: ❌ Error - {e}")

    console.print(f"🏁 Plugin test completed for {plugin_name}")


# Deprecated: 'podx podcast' removed in favor of YAML presets (podx config ...)


## (all 'podx podcast' subcommands removed)


## (removed)


## (removed)


## (removed)


## (removed)


@main.group("config")
def config_group():
    """Advanced YAML-based configuration management."""
    pass


@config_group.command("init")
def config_init():
    """Create an example YAML configuration file."""
    from rich.console import Console

    console = Console()
    manager = get_yaml_config_manager()

    # Check if config already exists
    if manager.config_file.exists():
        console.print(f"⚠️  Configuration file already exists at: {manager.config_file}")
        if not click.confirm("Overwrite existing configuration?"):
            console.print("Cancelled.")
            return

    # Create example config
    manager.create_example_config()
    console.print(
        f"✅ Created example YAML configuration at: [cyan]{manager.config_file}[/cyan]"
    )
    console.print("\n📝 Edit this file to customize your podcast processing settings:")
    console.print("   - Multiple Notion databases with different API keys")
    console.print("   - Podcast-specific analysis types and prompts")
    console.print("   - Global pipeline defaults")
    console.print("   - Custom variables and advanced settings")


@config_group.command("show")
def config_show():
    """Show current YAML configuration."""
    from rich.console import Console
    from rich.syntax import Syntax

    console = Console()
    manager = get_yaml_config_manager()

    if not manager.config_file.exists():
        console.print("❌ No YAML configuration found.")
        console.print("💡 Create one with [cyan]podx config init[/cyan]")
        return

    # Read and display config file
    config_content = manager.config_file.read_text()
    syntax = Syntax(config_content, "yaml", theme="monokai", line_numbers=True)

    console.print(f"📝 Configuration: [cyan]{manager.config_file}[/cyan]")
    console.print(syntax)


@config_group.command("validate")
def config_validate():
    """Validate YAML configuration syntax and settings."""
    from rich.console import Console

    console = Console()
    manager = get_yaml_config_manager()

    if not manager.config_file.exists():
        console.print("❌ No YAML configuration found.")
        return

    try:
        config = manager.load_config()
        console.print("✅ Configuration is valid!")

        # Show summary
        if config.podcasts:
            console.print(f"📋 Found {len(config.podcasts)} podcast mappings")
        if config.notion_databases:
            console.print(f"🗃️  Found {len(config.notion_databases)} Notion databases")
        if config.defaults:
            console.print("⚙️  Global defaults configured")

    except Exception as e:
        console.print(f"❌ Configuration validation failed: {e}")
        console.print("💡 Check your YAML syntax and fix any errors")


@config_group.command("databases")
def config_databases():
    """List configured Notion databases."""
    from rich.console import Console
    from rich.table import Table

    console = Console()
    manager = get_yaml_config_manager()
    databases = manager.list_notion_databases()

    if not databases:
        console.print("📭 No Notion databases configured.")
        console.print(
            f"💡 Add them to your YAML config: [cyan]{manager.config_file}[/cyan]"
        )
        return

    table = Table(title="🗃️ Configured Notion Databases")
    table.add_column("Name", style="cyan")
    table.add_column("Database ID", style="yellow")
    table.add_column("Token", style="magenta")
    table.add_column("Podcast Prop", style="green")
    table.add_column("Date Prop", style="green")
    table.add_column("Episode Prop", style="green")
    table.add_column("Description", style="blue")

    for name, db in databases.items():
        # Mask the database ID for security
        masked_id = (
            db.database_id[:8] + "..." + db.database_id[-8:]
            if len(db.database_id) > MIN_NOTION_DB_ID_LENGTH
            else db.database_id
        )

        def _mask(value: Optional[str]) -> str:
            if not value:
                return "(none)"
            if len(value) <= 10:
                return value
            return f"{value[:6]}…{value[-4:]}"

        masked_id = _mask(db.database_id)
        masked_token = _mask(db.token)

        table.add_row(
            name,
            masked_id,
            masked_token,
            db.podcast_property,
            db.date_property,
            db.episode_property,
            db.description or "No description",
        )

    console.print(table)


# ============================================================================
# Plugin Management Commands
# ============================================================================


@main.group("plugin", help="Manage podx plugins")
def plugin_group():
    """Plugin management commands."""
    pass


@plugin_group.command("list")
@click.option("--type", "-t", help="Filter by plugin type")
@click.option("--verbose", "-v", is_flag=True, help="Show detailed information")
def plugin_list(type, verbose):
    """List all available plugins."""
    from rich.console import Console
    from rich.table import Table

    from .plugins import PluginManager, PluginType

    console = Console()
    manager = PluginManager()

    # Discover all plugins
    manager.discover_plugins()

    # Filter by type if specified
    plugin_type_filter = None
    if type:
        try:
            plugin_type_filter = PluginType[type.upper()]
        except KeyError:
            console.print(f"❌ Invalid plugin type: {type}", style="red")
            console.print(f"Valid types: {', '.join([t.value for t in PluginType])}")
            return

    plugins = manager.get_available_plugins(plugin_type_filter)

    if not plugins:
        console.print("📭 No plugins found.")
        return

    # Create table
    if verbose:
        table = Table(title="🔌 Available Podx Plugins (Detailed)")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Version")
        table.add_column("Author")
        table.add_column("Description")
        table.add_column("Dependencies")

        for name, meta in sorted(plugins.items()):
            table.add_row(
                name,
                meta.plugin_type.value,
                meta.version,
                meta.author,
                meta.description,
                ", ".join(meta.dependencies) if meta.dependencies else "None",
            )
    else:
        table = Table(title="🔌 Available Podx Plugins")
        table.add_column("Name", style="cyan")
        table.add_column("Type", style="green")
        table.add_column("Version")
        table.add_column("Description")

        for name, meta in sorted(plugins.items()):
            table.add_row(
                name,
                meta.plugin_type.value,
                meta.version,
                meta.description,
            )

    console.print(table)
    console.print(f"\n✨ Total: {len(plugins)} plugin(s)")


@plugin_group.command("validate")
@click.argument("plugin_name")
@click.option("--config-file", "-c", help="Path to plugin configuration file (JSON)")
def plugin_validate(plugin_name, config_file):
    """Validate a plugin and its configuration."""
    from rich.console import Console

    from .plugins import PluginManager

    console = Console()
    manager = PluginManager()

    # Discover plugins
    manager.discover_plugins()

    # Get the plugin
    plugin = manager.registry.get_plugin(plugin_name)
    if not plugin:
        console.print(f"❌ Plugin '{plugin_name}' not found", style="red")
        return

    console.print(f"🔍 Validating plugin: [cyan]{plugin_name}[/cyan]")
    console.print()

    # Display metadata
    meta = plugin.metadata
    console.print(f"📦 Type: {meta.plugin_type.value}")
    console.print(f"📌 Version: {meta.version}")
    console.print(f"👤 Author: {meta.author}")
    console.print(f"📝 Description: {meta.description}")
    console.print()

    # Check dependencies
    if meta.dependencies:
        console.print("📚 Checking dependencies...")
        all_deps_ok = True
        for dep in meta.dependencies:
            try:
                __import__(dep.replace("-", "_"))
                console.print(f"  ✅ {dep}")
            except ImportError:
                console.print(f"  ❌ {dep} (not installed)", style="red")
                all_deps_ok = False

        if not all_deps_ok:
            console.print("\n⚠️  Some dependencies are missing. Install them to use this plugin.", style="yellow")
        console.print()

    # Validate configuration
    if config_file:
        console.print(f"⚙️  Validating configuration from: {config_file}")
        try:
            with open(config_file) as f:
                config = json.load(f)

            if plugin.validate_config(config):
                console.print("  ✅ Configuration is valid", style="green")

                # Try to initialize
                try:
                    plugin.initialize(config)
                    console.print("  ✅ Plugin initialized successfully", style="green")

                    # Test credentials if applicable
                    if hasattr(plugin, "validate_credentials"):
                        console.print("  🔐 Testing credentials...")
                        if plugin.validate_credentials():
                            console.print("  ✅ Credentials validated", style="green")
                        else:
                            console.print("  ❌ Credential validation failed", style="red")

                except Exception as e:
                    console.print(f"  ❌ Initialization failed: {e}", style="red")
            else:
                console.print("  ❌ Configuration is invalid", style="red")

        except FileNotFoundError:
            console.print(f"  ❌ Config file not found: {config_file}", style="red")
        except json.JSONDecodeError as e:
            console.print(f"  ❌ Invalid JSON: {e}", style="red")
        except Exception as e:
            console.print(f"  ❌ Validation error: {e}", style="red")
    else:
        console.print("💡 Tip: Use --config-file to validate a configuration")

    console.print()
    console.print("✅ Validation complete")


@plugin_group.command("create")
@click.argument("plugin_name")
@click.argument("plugin_type")
@click.option("--output-dir", "-o", default=".", help="Output directory for plugin file")
def plugin_create(plugin_name, plugin_type, output_dir):
    """Create a new plugin from template."""
    from rich.console import Console

    from .plugins import PluginType, create_plugin_template

    console = Console()

    # Validate plugin type
    try:
        ptype = PluginType[plugin_type.upper()]
    except KeyError:
        console.print(f"❌ Invalid plugin type: {plugin_type}", style="red")
        console.print(f"Valid types: {', '.join([t.value for t in PluginType])}")
        return

    # Create plugin template
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    try:
        plugin_file = create_plugin_template(ptype, plugin_name, output_path)
        console.print(f"✅ Plugin template created: [cyan]{plugin_file}[/cyan]", style="green")
        console.print()
        console.print("📝 Next steps:")
        console.print(f"  1. Edit the plugin file: {plugin_file}")
        console.print(f"  2. Implement required methods for {ptype.value} plugin")
        console.print(f"  3. Test your plugin with: podx plugin validate {plugin_name}")
        console.print("  4. Install your plugin in ~/.podx/plugins/ or use it locally")

    except Exception as e:
        console.print(f"❌ Failed to create plugin: {e}", style="red")


@plugin_group.command("types")
def plugin_types():
    """List all available plugin types."""
    from rich.console import Console
    from rich.table import Table

    from .plugins import PluginType

    console = Console()

    table = Table(title="🔌 Podx Plugin Types")
    table.add_column("Type", style="cyan")
    table.add_column("Value", style="green")
    table.add_column("Description")

    descriptions = {
        PluginType.SOURCE: "Alternative content sources (fetch podcasts from different platforms)",
        PluginType.AUDIO: "Audio processing and transcoding",
        PluginType.ASR: "Speech recognition / transcription",
        PluginType.ALIGNMENT: "Timing alignment",
        PluginType.DIARIZATION: "Speaker identification",
        PluginType.EXPORT: "Export to different formats",
        PluginType.ANALYSIS: "AI analysis and insights",
        PluginType.PUBLISH: "Publishing to different platforms",
        PluginType.PROCESSING: "Custom processing steps",
    }

    for ptype in PluginType:
        table.add_row(
            ptype.name,
            ptype.value,
            descriptions.get(ptype, ""),
        )

    console.print(table)


if __name__ == "__main__":
    main()
