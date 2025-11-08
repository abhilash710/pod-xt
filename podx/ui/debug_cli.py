"""Debug CLI command generation from PipelineConfig."""

from typing import Dict, Any
from ..domain import PipelineConfig
from ..config import get_config


def generate_debug_cli(config: PipelineConfig) -> str:
    """Generate CLI command from PipelineConfig with secret redaction.
    
    Args:
        config: Pipeline configuration
        
    Returns:
        CLI command string with secrets redacted
    """
    parts = ["podx run"]
    
    # Source options
    if config.show:
        parts.append(f'--show "{config.show}"')
    elif config.rss_url:
        parts.append(f'--rss-url "{config.rss_url}"')
    elif config.youtube_url:
        parts.append(f'--youtube-url "{config.youtube_url}"')
    
    if config.date:
        parts.append(f'--date "{config.date}"')
    if config.title_contains:
        parts.append(f'--title-contains "{config.title_contains}"')
    
    # Audio options
    fmt_value = config.fmt.value if hasattr(config.fmt, 'value') else config.fmt
    if fmt_value != "wav16":
        parts.append(f'--fmt {fmt_value}')
    
    # ASR options
    if config.model != get_config().default_asr_model:
        parts.append(f'--model "{config.model}"')
    if config.compute != "int8":
        parts.append(f'--compute {config.compute}')
    if config.asr_provider and config.asr_provider != "auto":
        provider_value = config.asr_provider.value if hasattr(config.asr_provider, 'value') else config.asr_provider
        parts.append(f'--asr-provider {provider_value}')
    
    # Pipeline flags
    if not config.diarize:
        parts.append("--no-diarize")
    if not config.preprocess:
        parts.append("--no-preprocess")
    if config.restore:
        parts.append("--restore")
    if not config.deepcast:
        parts.append("--no-deepcast")
    if not config.extract_markdown:
        parts.append("--no-markdown")
    if config.deepcast_pdf:
        parts.append("--deepcast-pdf")
    if config.notion:
        parts.append("--notion")
    
    # Deepcast options
    if config.deepcast_model != get_config().openai_model:
        parts.append(f'--deepcast-model "{config.deepcast_model}"')
    if config.deepcast_temp != get_config().openai_temperature:
        parts.append(f'--deepcast-temp {config.deepcast_temp}')
    
    # Notion options
    if config.notion_db:
        # Redact the database ID (show first 8 and last 8 chars)
        db_id = config.notion_db
        if len(db_id) > 16:
            redacted = f"{db_id[:8]}...{db_id[-8:]}"
        else:
            redacted = "***REDACTED***"
        parts.append(f'--db "{redacted}"')
    
    if config.podcast_prop != "Podcast":
        parts.append(f'--podcast-prop "{config.podcast_prop}"')
    if config.date_prop != "Date":
        parts.append(f'--date-prop "{config.date_prop}"')
    if config.episode_prop != "Episode":
        parts.append(f'--episode-prop "{config.episode_prop}"')
    
    if config.verbose:
        parts.append("--verbose")
    if config.clean:
        parts.append("--clean")
    if config.no_keep_audio:
        parts.append("--no-keep-audio")
    
    return " ".join(parts)

