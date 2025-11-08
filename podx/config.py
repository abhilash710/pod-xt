#!/usr/bin/env python3
"""
Centralized configuration management for podx.
"""

from typing import Optional

from pydantic import Field, validator
from pydantic_settings import BaseSettings


class PodxConfig(BaseSettings):
    """Main configuration for podx pipeline."""

    # ASR Configuration
    default_asr_model: str = Field(default="large-v3-turbo", env="PODX_DEFAULT_MODEL")
    default_compute: str = Field(default="int8", env="PODX_DEFAULT_COMPUTE")

    # OpenAI Configuration
    openai_api_key: Optional[str] = Field(default=None, env="OPENAI_API_KEY")
    openai_model: str = Field(default="gpt-4.1", env="OPENAI_MODEL")
    openai_temperature: float = Field(default=0.2, env="OPENAI_TEMPERATURE")
    openai_base_url: Optional[str] = Field(default=None, env="OPENAI_BASE_URL")

    # Notion Configuration
    notion_token: Optional[str] = Field(default=None, env="NOTION_TOKEN")
    notion_db_id: Optional[str] = Field(default=None, env="NOTION_DB_ID")
    notion_podcast_prop: str = Field(default="Podcast", env="NOTION_PODCAST_PROP")
    notion_date_prop: str = Field(default="Date", env="NOTION_DATE_PROP")
    notion_episode_prop: str = Field(default="Episode", env="NOTION_EPISODE_PROP")

    # Pipeline Configuration
    max_retries: int = Field(default=3, env="PODX_MAX_RETRIES")
    retry_delay: float = Field(default=1.0, env="PODX_RETRY_DELAY")
    chunk_chars: int = Field(default=24000, env="PODX_CHUNK_CHARS")

    # Pipeline Defaults (can be overridden by podcast-specific configs)
    default_align: bool = Field(default=False, env="PODX_DEFAULT_ALIGN")
    default_diarize: bool = Field(default=False, env="PODX_DEFAULT_DIARIZE")
    default_deepcast: bool = Field(default=False, env="PODX_DEFAULT_DEEPCAST")
    default_extract_markdown: bool = Field(
        default=False, env="PODX_DEFAULT_EXTRACT_MARKDOWN"
    )
    default_notion: bool = Field(default=False, env="PODX_DEFAULT_NOTION")
    default_podcast_type: Optional[str] = Field(
        default=None, env="PODX_DEFAULT_PODCAST_TYPE"
    )

    # Logging Configuration
    log_level: str = Field(default="INFO", env="PODX_LOG_LEVEL")
    log_format: str = Field(default="console", env="PODX_LOG_FORMAT")  # console, json

    # UI Configuration
    ui_enabled: bool = Field(default=True, env="PODX_UI_ENABLED")
    ui_port: int = Field(default=8000, env="PODX_UI_PORT")

    @validator("openai_temperature")
    def validate_temperature(cls, v):
        if not 0.0 <= v <= 2.0:
            raise ValueError("OpenAI temperature must be between 0.0 and 2.0")
        return v

    @validator("log_level")
    def validate_log_level(cls, v):
        valid_levels = {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}
        if v.upper() not in valid_levels:
            raise ValueError(f"Log level must be one of: {valid_levels}")
        return v.upper()

    @validator("log_format")
    def validate_log_format(cls, v):
        valid_formats = {"console", "json"}
        if v.lower() not in valid_formats:
            raise ValueError(f"Log format must be one of: {valid_formats}")
        return v.lower()

    class Config:
        env_file = ".env"
        case_sensitive = False
        extra = "ignore"  # Allow extra fields from env vars


# Global config instance
_config: Optional[PodxConfig] = None


def get_config() -> PodxConfig:
    """Get the global configuration instance."""
    global _config
    if _config is None:
        _config = PodxConfig()
    return _config


def reset_config() -> None:
    """Reset the global configuration (useful for testing)."""
    global _config
    _config = None
