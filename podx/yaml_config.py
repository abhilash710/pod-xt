#!/usr/bin/env python3
"""
YAML-based configuration system for podx with support for:
- Podcast-specific mappings and settings
- Multiple Notion databases with API keys
- Environment-specific configurations
- Hierarchical configuration inheritance
"""

import re
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, validator

from .prompt_templates import PodcastType


def format_database_id(db_id: str) -> str:
    """
    Format a database ID to UUID format if it's a 32-character string.

    Args:
        db_id: Database ID (either UUID format or 32-character string)

    Returns:
        Properly formatted UUID string
    """
    if not db_id:
        return db_id

    # Remove any existing hyphens to normalize
    clean_id = db_id.replace("-", "")

    # If it's not 32 hex characters, return as-is
    if len(clean_id) != 32 or not re.match(r"^[a-fA-F0-9]{32}$", clean_id):
        return db_id

    # Format as UUID: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
    return f"{clean_id[:8]}-{clean_id[8:12]}-{clean_id[12:16]}-{clean_id[16:20]}-{clean_id[20:]}"


# Configure YAML to handle PodcastType enums
def podcast_type_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data.value)


def podcast_type_constructor(loader, node):
    value = loader.construct_scalar(node)
    return PodcastType(value)


yaml.add_representer(PodcastType, podcast_type_representer)
yaml.add_constructor("tag:yaml.org,2002:str", podcast_type_constructor)


class NotionDatabase(BaseModel):
    """Configuration for a specific Notion database."""

    name: str = Field(..., description="Friendly name for this database")
    database_id: str = Field(..., description="Notion database ID")
    token: str = Field(..., description="Notion integration token")
    podcast_property: str = Field(
        default="Podcast", description="Property name for podcast name"
    )
    date_property: str = Field(
        default="Date", description="Property name for episode date"
    )
    episode_property: str = Field(
        default="Episode", description="Property name for episode title"
    )
    tags_property: Optional[str] = Field(
        default="Tags", description="Property name for tags/keywords"
    )
    model_property: Optional[str] = Field(
        default="Model", description="Property name for deepcast model used"
    )
    description: Optional[str] = Field(default=None, description="Database description")

    @validator("database_id")
    def format_database_id_validator(cls, v):
        """Format database ID to proper UUID format if needed."""
        return format_database_id(v)


class AnalysisConfig(BaseModel):
    """Configuration for AI analysis settings."""

    type: PodcastType = Field(default=PodcastType.GENERAL, description="Analysis type")
    model: Optional[str] = Field(default=None, description="OpenAI model override")
    temperature: Optional[float] = Field(
        default=None, description="Temperature override"
    )
    chunk_size: Optional[int] = Field(default=None, description="Chunk size override")
    custom_prompts: Optional[str] = Field(
        default=None, description="Custom prompt additions"
    )

    @validator("temperature")
    def validate_temperature(cls, v):
        if v is not None and not 0.0 <= v <= 2.0:
            raise ValueError("Temperature must be between 0.0 and 2.0")
        return v


class PipelineDefaults(BaseModel):
    """Default pipeline settings."""

    align: bool = Field(default=False, description="Enable alignment by default")
    diarize: bool = Field(default=False, description="Enable diarization by default")
    deepcast: bool = Field(default=False, description="Enable AI analysis by default")
    extract_markdown: bool = Field(
        default=False, description="Extract markdown by default"
    )
    notion: bool = Field(default=False, description="Upload to Notion by default")
    clean: bool = Field(
        default=False, description="Clean intermediate files by default"
    )


class PodcastMapping(BaseModel):
    """Configuration mapping for a specific podcast."""

    # Identification
    names: List[str] = Field(..., description="Show names and aliases")

    # Analysis settings
    analysis: Optional[AnalysisConfig] = Field(
        default=None, description="Analysis configuration"
    )

    # Pipeline settings
    pipeline: Optional[PipelineDefaults] = Field(
        default=None, description="Pipeline defaults"
    )

    # Notion settings
    notion_database: Optional[str] = Field(
        default=None, description="Notion database name to use"
    )

    # Custom settings
    description: Optional[str] = Field(default=None, description="Mapping description")
    tags: Optional[List[str]] = Field(
        default=None, description="Custom tags for this podcast"
    )


class PodxYamlConfig(BaseModel):
    """Complete YAML configuration for podx."""

    # Global settings
    version: str = Field(default="1.0", description="Config file version")

    # Environment settings
    environment: Optional[str] = Field(
        default=None, description="Environment name (dev, prod, etc.)"
    )

    # Default pipeline settings
    defaults: Optional[PipelineDefaults] = Field(
        default=None, description="Global pipeline defaults"
    )

    # Analysis defaults
    analysis: Optional[AnalysisConfig] = Field(
        default=None, description="Global analysis defaults"
    )

    # Notion databases
    notion_databases: Optional[Dict[str, NotionDatabase]] = Field(
        default=None, description="Named Notion database configurations"
    )

    # Podcast mappings
    podcasts: Optional[Dict[str, PodcastMapping]] = Field(
        default=None, description="Podcast-specific configurations"
    )

    # Custom variables (for templating, future use)
    variables: Optional[Dict[str, Any]] = Field(
        default=None, description="Custom variables for configuration"
    )


class YamlConfigManager:
    """Manages YAML-based configuration files."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path.home() / ".podx"
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.config_dir / "config.yaml"
        self._config: Optional[PodxYamlConfig] = None

    def load_config(self) -> PodxYamlConfig:
        """Load configuration from YAML file."""
        if self._config is not None:
            return self._config

        if not self.config_file.exists():
            # Create default config if none exists
            self._config = PodxYamlConfig()
            self.save_config(self._config)
            return self._config

        try:
            with open(self.config_file, "r") as f:
                data = yaml.safe_load(f)

            if not data:
                self._config = PodxYamlConfig()
            else:
                self._config = PodxYamlConfig(**data)

            return self._config
        except Exception as e:
            print(f"Warning: Failed to load YAML config: {e}")
            print("Using default configuration...")
            self._config = PodxYamlConfig()
            return self._config

    def save_config(self, config: PodxYamlConfig) -> None:
        """Save configuration to YAML file."""
        with open(self.config_file, "w") as f:
            # Convert to dict and remove None values for cleaner output
            config_dict = config.model_dump(exclude_none=True, mode="json")
            yaml.dump(
                config_dict, f, default_flow_style=False, sort_keys=False, indent=2
            )

        # Invalidate cache
        self._config = None

    def get_podcast_config(self, show_name: str) -> Optional[PodcastMapping]:
        """Get configuration for a specific podcast."""
        config = self.load_config()

        if not config or not config.podcasts:
            return None

        # Direct key match
        if show_name in config.podcasts:
            return config.podcasts[show_name]

        # Search by name aliases
        show_lower = show_name.lower()
        for mapping in config.podcasts.values():
            for name in mapping.names:
                if name.lower() == show_lower:
                    return mapping

        return None

    def get_notion_database(self, database_name: str) -> Optional[NotionDatabase]:
        """Get Notion database configuration by name."""
        config = self.load_config()

        if not config.notion_databases:
            return None

        return config.notion_databases.get(database_name)

    def list_notion_databases(self) -> Dict[str, NotionDatabase]:
        """List all configured Notion databases."""
        config = self.load_config()
        return config.notion_databases or {}

    def add_podcast_mapping(self, key: str, mapping: PodcastMapping) -> None:
        """Add or update a podcast mapping."""
        config = self.load_config()

        if config.podcasts is None:
            config.podcasts = {}

        config.podcasts[key] = mapping
        self.save_config(config)

    def add_notion_database(self, name: str, database: NotionDatabase) -> None:
        """Add or update a Notion database configuration."""
        config = self.load_config()

        if config.notion_databases is None:
            config.notion_databases = {}

        config.notion_databases[name] = database
        self.save_config(config)

    def create_example_config(self) -> None:
        """Create an example configuration file."""
        example_config = PodxYamlConfig(
            version="1.0",
            environment="development",
            # Global defaults
            defaults=PipelineDefaults(
                align=True, deepcast=True, extract_markdown=True, notion=False
            ),
            # Global analysis settings
            analysis=AnalysisConfig(
                type=PodcastType.GENERAL, model="gpt-4.1-mini", temperature=0.2
            ),
            # Notion databases
            notion_databases={
                "personal": NotionDatabase(
                    name="Personal Podcast Library",
                    database_id="your-personal-db-id-here",
                    token="your-personal-notion-token",
                    podcast_property="Podcast",
                    date_property="Date",
                    episode_property="Episode",
                    tags_property="Tags",
                    description="Personal podcast collection",
                ),
                "work": NotionDatabase(
                    name="Work Knowledge Base",
                    database_id="your-work-db-id-here",
                    token="your-work-notion-token",
                    podcast_property="Podcast",
                    date_property="Date",
                    episode_property="Episode",
                    tags_property="Keywords",
                    description="Work-related podcast insights",
                ),
            },
            # Podcast mappings
            podcasts={
                "lenny": PodcastMapping(
                    names=["Lenny's Podcast", "Lenny's Newsletter", "Lenny Rachitsky"],
                    analysis=AnalysisConfig(
                        type=PodcastType.INTERVIEW_GUEST_FOCUSED,
                        custom_prompts="""
                        SPECIAL FOCUS for Lenny's Podcast:
                        - Product management interview format
                        - Prioritize guest insights about strategy, growth, and tactics
                        - Extract frameworks, metrics, and case studies
                        - Note specific tools and resources mentioned
                        """,
                    ),
                    pipeline=PipelineDefaults(
                        align=True, deepcast=True, extract_markdown=True, notion=True
                    ),
                    notion_database="work",
                    description="Product management interviews",
                    tags=["product", "growth", "strategy"],
                ),
                "lex": PodcastMapping(
                    names=[
                        "Lex Fridman Podcast",
                        "Lex Fridman",
                        "Artificial Intelligence Podcast",
                    ],
                    analysis=AnalysisConfig(
                        type=PodcastType.INTERVIEW_HOST_FOCUSED,
                        temperature=0.3,
                        custom_prompts="""
                        SPECIAL FOCUS for Lex Fridman Podcast:
                        - Capture Lex's thoughtful questions and philosophical frameworks
                        - Balance technical insights with human elements
                        - Note both deep technical discussions and personal reflections
                        """,
                    ),
                    pipeline=PipelineDefaults(
                        align=True,
                        deepcast=True,
                        extract_markdown=True,
                        notion=False,  # Too long for regular notion upload
                    ),
                    notion_database="personal",
                    description="Long-form intellectual interviews",
                    tags=["ai", "philosophy", "science"],
                ),
                "business": PodcastMapping(
                    names=[
                        "Y Combinator Podcast",
                        "YC Podcast",
                        "The Tim Ferriss Show",
                    ],
                    analysis=AnalysisConfig(type=PodcastType.BUSINESS),
                    pipeline=PipelineDefaults(
                        align=True, deepcast=True, extract_markdown=True, notion=True
                    ),
                    notion_database="work",
                    description="Business and entrepreneurship content",
                    tags=["business", "entrepreneurship", "startup"],
                ),
            },
            # Custom variables
            variables={
                "author": "Your Name",
                "default_language": "en",
                "transcription_model": "large-v2",
            },
        )

        self.save_config(example_config)


# Global YAML config manager
_yaml_manager: Optional[YamlConfigManager] = None


def get_yaml_config_manager() -> YamlConfigManager:
    """Get the global YAML configuration manager."""
    global _yaml_manager
    if _yaml_manager is None:
        _yaml_manager = YamlConfigManager()
    return _yaml_manager


def load_yaml_config() -> PodxYamlConfig:
    """Load the YAML configuration."""
    return get_yaml_config_manager().load_config()


def get_podcast_yaml_config(show_name: str) -> Optional[PodcastMapping]:
    """Get YAML-based podcast configuration."""
    return get_yaml_config_manager().get_podcast_config(show_name)


def get_notion_database_config(database_name: str) -> Optional[NotionDatabase]:
    """Get Notion database configuration by name."""
    return get_yaml_config_manager().get_notion_database(database_name)
