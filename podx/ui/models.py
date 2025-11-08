"""Pydantic models for PodX Studio API."""

from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field


class AdvancedOptions(BaseModel):
    """Advanced pipeline options."""
    diarize: bool = True
    deepcast: bool = True
    preprocess: bool = True
    restore: bool = False
    extract_markdown: bool = True
    deepcast_pdf: bool = False
    notion: bool = False
    model: str = "large-v3-turbo"
    compute: str = "int8"
    asr_provider: str = "auto"
    deepcast_model: str = "gpt-4.1"
    deepcast_temp: float = 0.2
    analysis_type: Optional[str] = None


class RunRequest(BaseModel):
    """Request to start a new pipeline run."""
    url: str = Field(..., description="Podcast URL (RSS, YouTube, or podcast page)")
    preset: Optional[str] = Field(None, description="Preset name to apply")
    advanced: Optional[AdvancedOptions] = Field(None, description="Advanced options")


class RunResponse(BaseModel):
    """Response after starting a run."""
    run_id: str = Field(..., description="Unique run identifier")


class RunStatus(BaseModel):
    """Status of a pipeline run."""
    run_id: str
    status: str  # pending, running, completed, failed, canceled
    progress: Dict[str, str] = Field(default_factory=dict)  # stage -> status
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    started_at: str  # ISO format datetime
    completed_at: Optional[str] = None  # ISO format datetime
    notion_url: Optional[str] = None


class PresetResponse(BaseModel):
    """Preset information."""
    name: str
    config: Dict[str, Any]


class PresetCreateRequest(BaseModel):
    """Request to create a preset."""
    name: str
    config: Dict[str, Any]


class UrlValidationResponse(BaseModel):
    """URL validation response."""
    valid: bool
    type: str  # youtube, rss, podcast_page, invalid
    error: Optional[str] = None


class HealthResponse(BaseModel):
    """Health check response."""
    status: str = "ok"
    version: str = "2.0.0"


class ArtifactInfo(BaseModel):
    """Information about an artifact."""
    name: str
    path: str
    size: Optional[int] = None
    type: str  # transcript, audio, analysis, export


class ArtifactsResponse(BaseModel):
    """List of artifacts for a run."""
    artifacts: List[ArtifactInfo]

