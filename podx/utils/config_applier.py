"""Apply podcast-specific configuration from YAML or JSON config files."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

from ..config import get_config
from ..podcast_config import get_podcast_config
from ..yaml_config import get_notion_database_config, get_podcast_yaml_config


class ConfigResult:
    """Result of applying podcast configuration."""

    def __init__(
        self,
        flags: Dict[str, Any],
        deepcast_model: str,
        deepcast_temp: float,
        yaml_analysis_type: Optional[str] = None,
        notion_db: Optional[str] = None,
    ):
        self.flags = flags
        self.deepcast_model = deepcast_model
        self.deepcast_temp = deepcast_temp
        self.yaml_analysis_type = yaml_analysis_type
        self.notion_db = notion_db


def apply_podcast_config(
    show_name: str,
    current_flags: Dict[str, Any],
    deepcast_model: str,
    deepcast_temp: float,
    notion: bool,
    logger,
) -> ConfigResult:
    """Apply podcast-specific configuration from YAML or JSON files.

    Args:
        show_name: Name of the podcast show
        current_flags: Current pipeline flags (diarize, deepcast, etc.)
        deepcast_model: Current deepcast model
        deepcast_temp: Current deepcast temperature
        notion: Whether Notion upload is enabled
        logger: Logger instance for info messages

    Returns:
        ConfigResult with updated flags and configuration
    """
    # Try YAML config first, then fall back to JSON config
    yaml_config = get_podcast_yaml_config(show_name) if show_name else None
    json_config = get_podcast_config(show_name) if show_name else None

    # Initialize return values
    updated_flags = current_flags.copy()
    yaml_analysis_type = None
    notion_db = None

    # Apply podcast-specific defaults (YAML takes precedence over JSON)
    active_config = yaml_config or json_config
    config_type = "YAML" if yaml_config else "JSON" if json_config else None

    if not active_config:
        return ConfigResult(
            flags=updated_flags,
            deepcast_model=deepcast_model,
            deepcast_temp=deepcast_temp,
            yaml_analysis_type=yaml_analysis_type,
            notion_db=notion_db,
        )

    # Apply YAML configuration
    if yaml_config:
        logger.info(
            "Found YAML podcast configuration",
            show=show_name,
            config_type=config_type,
        )

        # Apply YAML pipeline defaults
        if yaml_config.pipeline:
            if not updated_flags.get("diarize") and yaml_config.pipeline.diarize:
                updated_flags["diarize"] = True
                logger.info("Applied YAML config: diarize = True")
            if not updated_flags.get("deepcast") and yaml_config.pipeline.deepcast:
                updated_flags["deepcast"] = True
                logger.info("Applied YAML config: deepcast = True")
            if (
                not updated_flags.get("extract_markdown")
                and yaml_config.pipeline.extract_markdown
            ):
                updated_flags["extract_markdown"] = True
                logger.info("Applied YAML config: extract_markdown = True")
            if not updated_flags.get("notion") and yaml_config.pipeline.notion:
                updated_flags["notion"] = True
                logger.info("Applied YAML config: notion = True")

        # Apply YAML analysis settings
        if yaml_config.analysis:
            base_config = get_config()
            if (
                deepcast_model == base_config.openai_model
                and yaml_config.analysis.model
            ):
                deepcast_model = yaml_config.analysis.model
                logger.info("Applied YAML config model", model=deepcast_model)
            if (
                abs(deepcast_temp - base_config.openai_temperature) < 0.001
                and yaml_config.analysis.temperature
            ):
                deepcast_temp = yaml_config.analysis.temperature
                logger.info(
                    "Applied YAML config temperature", temperature=deepcast_temp
                )
            # Store analysis type for later use in deepcast
            if yaml_config.analysis.type:
                yaml_analysis_type = yaml_config.analysis.type.value
                logger.info(
                    "Applied YAML config analysis type", type=yaml_analysis_type
                )

        # Handle Notion database selection
        if yaml_config.notion_database and notion:
            notion_db_config = get_notion_database_config(
                yaml_config.notion_database
            )
            if notion_db_config:
                notion_db = notion_db_config.database_id
                logger.info(
                    "Applied YAML Notion database",
                    database=yaml_config.notion_database,
                )
                # Set environment variables for the token
                os.environ["NOTION_TOKEN"] = notion_db_config.token
                os.environ["NOTION_PODCAST_PROP"] = (
                    notion_db_config.podcast_property
                )
                os.environ["NOTION_DATE_PROP"] = notion_db_config.date_property
                os.environ["NOTION_EPISODE_PROP"] = (
                    notion_db_config.episode_property
                )

    # Apply JSON configuration
    elif json_config:
        logger.info(
            "Found JSON podcast configuration",
            show=show_name,
            config_type=json_config.podcast_type.value,
        )

        # Apply JSON defaults (original logic)
        config_flags = json_config.default_flags

        if not updated_flags.get("diarize") and config_flags.get("diarize", False):
            updated_flags["diarize"] = True
            logger.info("Applied JSON config: diarize = True")
        if not updated_flags.get("deepcast") and config_flags.get("deepcast", False):
            updated_flags["deepcast"] = True
            logger.info("Applied JSON config: deepcast = True")
        if not updated_flags.get("extract_markdown") and (
            config_flags.get("extract_markdown", False)
            or json_config.extract_markdown
        ):
            updated_flags["extract_markdown"] = True
            logger.info("Applied JSON config: extract_markdown = True")
        if not updated_flags.get("notion") and (
            config_flags.get("notion", False) or json_config.notion_upload
        ):
            updated_flags["notion"] = True
            logger.info("Applied JSON config: notion = True")

        # Apply model preferences
        base_config = get_config()
        if (
            deepcast_model == base_config.openai_model
            and json_config.deepcast_model
        ):
            deepcast_model = json_config.deepcast_model
            logger.info("Applied JSON config model", model=deepcast_model)
        if (
            abs(deepcast_temp - base_config.openai_temperature) < 0.001
            and json_config.temperature
        ):
            deepcast_temp = json_config.temperature
            logger.info(
                "Applied JSON config temperature", temperature=deepcast_temp
            )

    return ConfigResult(
        flags=updated_flags,
        deepcast_model=deepcast_model,
        deepcast_temp=deepcast_temp,
        yaml_analysis_type=yaml_analysis_type,
        notion_db=notion_db,
    )
