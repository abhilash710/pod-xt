"""API route handlers for PodX Studio."""

import json
import asyncio
from pathlib import Path
from typing import Dict, Any, Optional

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse, StreamingResponse

from .models import (
    RunRequest,
    RunResponse,
    RunStatus,
    PresetResponse,
    PresetCreateRequest,
    UrlValidationResponse,
    HealthResponse,
    ArtifactsResponse,
    ArtifactInfo,
)
from .run_manager import RunManager
from .preset_manager import PresetManager
from .url_validator import validate_url
from .debug_cli import generate_debug_cli
from ..domain import PipelineConfig
from ..services import AsyncPipelineService
from ..config import get_config
from ..logging import get_logger

logger = get_logger(__name__)

router = APIRouter()

# Global managers (initialized in server startup)
run_manager: Optional[RunManager] = None
preset_manager: Optional[PresetManager] = None
websocket_connections: Dict[str, list] = {}  # run_id -> list of WebSocket connections


def init_managers():
    """Initialize global managers."""
    global run_manager, preset_manager
    run_manager = RunManager()
    preset_manager = PresetManager()


def _url_to_config(url: str, advanced: Optional[Dict[str, Any]] = None) -> PipelineConfig:
    """Convert URL and advanced options to PipelineConfig.
    
    Args:
        url: Podcast URL
        advanced: Advanced options dictionary
        
    Returns:
        PipelineConfig object
    """
    # Detect URL type
    validation = validate_url(url)
    if not validation["valid"]:
        raise ValueError(f"Invalid URL: {validation.get('error')}")
    
    url_type = validation["type"]
    
    # Build config based on URL type
    config_dict = {
        "verbose": False,
        "clean": False,
        "no_keep_audio": False,
    }
    
    if url_type == "youtube":
        config_dict["youtube_url"] = url
    elif url_type == "rss":
        config_dict["rss_url"] = url
    else:
        # Podcast page - try to extract RSS or use as show name
        # For now, treat as RSS URL (user should provide RSS)
        config_dict["rss_url"] = url
    
    # Apply advanced options if provided
    if advanced:
        config_dict.update(advanced)
    
    # Apply defaults from config
    cfg = get_config()
    if "model" not in config_dict:
        config_dict["model"] = cfg.default_asr_model
    if "compute" not in config_dict:
        config_dict["compute"] = cfg.default_compute
    if "deepcast_model" not in config_dict:
        config_dict["deepcast_model"] = cfg.openai_model
    if "deepcast_temp" not in config_dict:
        config_dict["deepcast_temp"] = cfg.openai_temperature
    
    # Set Notion DB if notion is enabled
    if config_dict.get("notion") and cfg.notion_db_id:
        config_dict["notion_db"] = cfg.notion_db_id
        config_dict["podcast_prop"] = cfg.notion_podcast_prop
        config_dict["date_prop"] = cfg.notion_date_prop
        config_dict["episode_prop"] = cfg.notion_episode_prop
    
    return PipelineConfig(**config_dict)


@router.post("/api/runs", response_model=RunResponse)
async def create_run(request: RunRequest):
    """Start a new pipeline run."""
    if not run_manager:
        raise HTTPException(status_code=500, detail="Run manager not initialized")
    
    try:
        # Get preset config if specified
        advanced_dict = None
        if request.preset:
            preset = preset_manager.get_preset(request.preset) if preset_manager else None
            if not preset:
                raise HTTPException(status_code=404, detail=f"Preset '{request.preset}' not found")
            advanced_dict = preset.config
        
        # Merge with request advanced options
        if request.advanced:
            # Convert Pydantic model to dict
            if hasattr(request.advanced, 'model_dump'):
                advanced_dict_new = request.advanced.model_dump(exclude_unset=True)
            else:
                advanced_dict_new = request.advanced.dict(exclude_unset=True)
            if advanced_dict:
                advanced_dict.update(advanced_dict_new)
            else:
                advanced_dict = advanced_dict_new
        
        # Convert to PipelineConfig
        config = _url_to_config(request.url, advanced_dict)
        
        # Create run
        run_id = run_manager.create_run(config)
        
        # Start pipeline execution in background
        asyncio.create_task(_execute_pipeline(run_id, config))
        
        return RunResponse(run_id=run_id)
    except RuntimeError as e:
        raise HTTPException(status_code=429, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Failed to create run", error=str(e))
        raise HTTPException(status_code=500, detail=str(e))


async def _execute_pipeline(run_id: str, config: PipelineConfig):
    """Execute pipeline in background and send progress updates."""
    if not run_manager:
        return
    
    run = run_manager.get_run(run_id)
    if not run:
        return
    
    try:
        run_manager.update_run_status(run_id, "running")
        await _send_progress(run_id, "fetch", "started")
        
        # Create progress callback
        async def progress_callback(step: str, status: str):
            # Map pipeline steps to UI stages
            stage_map = {
                "fetch": "fetch",
                "transcode": "transcode",
                "transcribe": "transcribe",
                "preprocess": "preprocess",
                "align": "preprocess",  # Alignment is part of preprocessing in UI
                "diarize": "diarize",
                "deepcast": "deepcast",
                "export": "export",
                "notion": "notion",
            }
            stage = stage_map.get(step, step)
            
            # Normalize status messages to status codes
            status_lower = status.lower()
            if "started" in status_lower or "fetching" in status_lower or "transcoding" in status_lower or "transcribing" in status_lower:
                normalized_status = "started"
            elif "completed" in status_lower or "using existing" in status_lower:
                normalized_status = "completed"
            elif "failed" in status_lower or "error" in status_lower:
                normalized_status = "failed"
            else:
                normalized_status = "started"  # Default to started for unknown messages
            
            await _send_progress(run_id, stage, normalized_status)
            run_manager.update_run_progress(run_id, stage, normalized_status)
        
        # Execute pipeline
        service = AsyncPipelineService(config)
        result = await service.execute(progress_callback=progress_callback)
        
        # Update run with result
        run_manager.set_run_result(run_id, result)
        
        # Extract Notion URL if available
        if result.artifacts.get("notion"):
            notion_file = Path(result.artifacts["notion"])
            if notion_file.exists():
                try:
                    notion_data = json.loads(notion_file.read_text())
                    notion_url = notion_data.get("url") or notion_data.get("page_url")
                    if notion_url:
                        run_manager.set_notion_url(run_id, notion_url)
                except Exception:
                    pass
        
        # Save to history
        run = run_manager.get_run(run_id)
        if run:
            run_manager.save_to_history(run)
        
        await _send_progress(run_id, "complete", "completed")
    except asyncio.CancelledError:
        run_manager.update_run_status(run_id, "canceled")
        await _send_progress(run_id, "canceled", "canceled")
    except Exception as e:
        error_msg = str(e)
        run_manager.set_run_error(run_id, error_msg)
        await _send_progress(run_id, "error", "failed")
        logger.error("Pipeline execution failed", run_id=run_id, error=error_msg)


async def _send_progress(run_id: str, stage: str, status: str):
    """Send progress update to WebSocket connections."""
    if run_id not in websocket_connections:
        return
    
    run = run_manager.get_run(run_id) if run_manager else None
    if not run:
        return
    
    message = {
        "stage": stage,
        "status": status,
        "progress": run.progress.copy(),
    }
    
    # Send to all connected clients
    disconnected = []
    for ws in websocket_connections[run_id]:
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.append(ws)
    
    # Remove disconnected clients
    for ws in disconnected:
        websocket_connections[run_id].remove(ws)


@router.get("/api/runs", response_model=list[RunStatus])
async def list_runs():
    """List recent runs."""
    if not run_manager:
        raise HTTPException(status_code=500, detail="Run manager not initialized")
    
    runs = run_manager.list_recent_runs()
    return [RunStatus(**run.to_dict()) for run in runs]


@router.get("/api/runs/{run_id}", response_model=RunStatus)
async def get_run(run_id: str):
    """Get run details."""
    if not run_manager:
        raise HTTPException(status_code=500, detail="Run manager not initialized")
    
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    
    return RunStatus(**run.to_dict())


@router.post("/api/runs/{run_id}/cancel")
async def cancel_run(run_id: str):
    """Cancel an active run."""
    if not run_manager:
        raise HTTPException(status_code=500, detail="Run manager not initialized")
    
    success = run_manager.cancel_run(run_id)
    if not success:
        raise HTTPException(status_code=400, detail="Run cannot be canceled")
    
    return {"status": "canceled"}


@router.get("/api/runs/{run_id}/artifacts", response_model=ArtifactsResponse)
async def list_artifacts(run_id: str):
    """List artifacts for a run."""
    if not run_manager:
        raise HTTPException(status_code=500, detail="Run manager not initialized")
    
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    
    if not run.result:
        return ArtifactsResponse(artifacts=[])
    
    artifacts = []
    for name, path_str in run.result.artifacts.items():
        path = Path(path_str)
        if path.exists():
            size = path.stat().st_size if path.is_file() else None
            artifact_type = _get_artifact_type(name, path)
            artifacts.append(ArtifactInfo(
                name=name,
                path=str(path),
                size=size,
                type=artifact_type
            ))
    
    return ArtifactsResponse(artifacts=artifacts)


def _get_artifact_type(name: str, path: Path) -> str:
    """Determine artifact type from name and path."""
    name_lower = name.lower()
    suffix = path.suffix.lower()
    
    if "transcript" in name_lower or suffix == ".json":
        return "transcript"
    elif "audio" in name_lower or suffix in (".wav", ".mp3", ".aac"):
        return "audio"
    elif "deepcast" in name_lower or "analysis" in name_lower:
        return "analysis"
    elif suffix in (".txt", ".srt", ".vtt", ".md", ".pdf"):
        return "export"
    else:
        return "other"


@router.get("/api/runs/{run_id}/transcript")
async def get_transcript(run_id: str):
    """Get transcript JSON for a run."""
    if not run_manager:
        raise HTTPException(status_code=500, detail="Run manager not initialized")
    
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    
    if not run.result:
        raise HTTPException(status_code=404, detail="Run has no result")
    
    transcript_path = run.result.artifacts.get("transcript") or run.result.artifacts.get("latest_json")
    if not transcript_path:
        raise HTTPException(status_code=404, detail="Transcript not found")
    
    path = Path(transcript_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Transcript file not found")
    
    return FileResponse(path, media_type="application/json")


@router.get("/api/runs/{run_id}/export/{format}")
async def export_artifact(run_id: str, format: str):
    """Export artifact in specified format."""
    if not run_manager:
        raise HTTPException(status_code=500, detail="Run manager not initialized")
    
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    
    if not run.result:
        raise HTTPException(status_code=404, detail="Run has no result")
    
    # Map format to artifact key
    format_map = {
        "txt": "latest_txt",
        "json": "latest_json",
        "srt": "latest_srt",
        "vtt": "latest_vtt",
        "md": "deepcast_md",
    }
    
    artifact_key = format_map.get(format.lower())
    if not artifact_key:
        raise HTTPException(status_code=400, detail=f"Unsupported format: {format}")
    
    artifact_path = run.result.artifacts.get(artifact_key)
    if not artifact_path:
        raise HTTPException(status_code=404, detail=f"Artifact '{format}' not found")
    
    path = Path(artifact_path)
    if not path.exists():
        raise HTTPException(status_code=404, detail="Artifact file not found")
    
    media_types = {
        "txt": "text/plain",
        "json": "application/json",
        "srt": "text/srt",
        "vtt": "text/vtt",
        "md": "text/markdown",
    }
    
    return FileResponse(path, media_type=media_types.get(format, "application/octet-stream"))


@router.get("/api/runs/{run_id}/export/zip")
async def export_zip(run_id: str):
    """Export all artifacts as ZIP."""
    import zipfile
    import io
    
    if not run_manager:
        raise HTTPException(status_code=500, detail="Run manager not initialized")
    
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    
    if not run.result:
        raise HTTPException(status_code=404, detail="Run has no result")
    
    # Create ZIP in memory
    zip_buffer = io.BytesIO()
    with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
        for name, path_str in run.result.artifacts.items():
            path = Path(path_str)
            if path.exists() and path.is_file():
                zip_file.write(path, path.name)
    
    zip_buffer.seek(0)
    
    return StreamingResponse(
        zip_buffer,
        media_type="application/zip",
        headers={"Content-Disposition": f"attachment; filename=podx-run-{run_id}.zip"}
    )


@router.get("/api/presets", response_model=list[PresetResponse])
async def list_presets():
    """List all presets."""
    if not preset_manager:
        raise HTTPException(status_code=500, detail="Preset manager not initialized")
    
    presets = preset_manager.list_presets()
    return [PresetResponse(name=p.name, config=p.config) for p in presets]


@router.post("/api/presets", response_model=PresetResponse)
async def create_preset(request: PresetCreateRequest):
    """Create a new preset."""
    if not preset_manager:
        raise HTTPException(status_code=500, detail="Preset manager not initialized")
    
    try:
        preset = preset_manager.create_preset(request.name, request.config)
        return PresetResponse(name=preset.name, config=preset.config)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/api/presets/{name}")
async def delete_preset(name: str):
    """Delete a preset."""
    if not preset_manager:
        raise HTTPException(status_code=500, detail="Preset manager not initialized")
    
    try:
        success = preset_manager.delete_preset(name)
        if not success:
            raise HTTPException(status_code=404, detail=f"Preset '{name}' not found")
        return {"status": "deleted"}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/api/validate-url", response_model=UrlValidationResponse)
async def validate_url_endpoint(url: str):
    """Validate a URL and detect its type."""
    result = validate_url(url)
    return UrlValidationResponse(**result)


@router.get("/api/runs/{run_id}/debug-cli")
async def get_debug_cli(run_id: str):
    """Get debug CLI command for a run."""
    if not run_manager:
        raise HTTPException(status_code=500, detail="Run manager not initialized")
    
    run = run_manager.get_run(run_id)
    if not run:
        raise HTTPException(status_code=404, detail=f"Run '{run_id}' not found")
    
    cli_command = generate_debug_cli(run.config)
    return {"command": cli_command}


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint."""
    return HealthResponse()


@router.websocket("/ws/{run_id}")
async def websocket_endpoint(websocket: WebSocket, run_id: str):
    """WebSocket endpoint for progress updates."""
    await websocket.accept()
    
    if run_id not in websocket_connections:
        websocket_connections[run_id] = []
    
    websocket_connections[run_id].append(websocket)
    
    try:
        # Send initial state
        if run_manager:
            run = run_manager.get_run(run_id)
            if run:
                await websocket.send_json({
                    "stage": "connected",
                    "status": run.status,
                    "progress": run.progress.copy(),
                })
        
        # Keep connection alive
        while True:
            try:
                # Wait for ping or close
                data = await websocket.receive_text()
                if data == "ping":
                    await websocket.send_text("pong")
            except WebSocketDisconnect:
                break
    except Exception as e:
        logger.error("WebSocket error", run_id=run_id, error=str(e))
    finally:
        if run_id in websocket_connections:
            websocket_connections[run_id].remove(websocket)
            if not websocket_connections[run_id]:
                del websocket_connections[run_id]

