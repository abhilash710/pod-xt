"""Unit tests for PodX Studio URL validator."""

import pytest
from podx.ui.url_validator import validate_url


def test_validate_youtube_url():
    """Test YouTube URL validation."""
    result = validate_url("https://www.youtube.com/watch?v=dQw4w9WgXcQ")
    assert result["valid"] is True
    assert result["type"] == "youtube"
    assert result["error"] is None


def test_validate_rss_url():
    """Test RSS feed URL validation."""
    result = validate_url("https://example.com/feed.xml")
    assert result["valid"] is True
    assert result["type"] == "rss"
    assert result["error"] is None


def test_validate_podcast_page_url():
    """Test podcast page URL validation."""
    result = validate_url("https://example.com/podcast")
    assert result["valid"] is True
    assert result["type"] == "podcast_page"
    assert result["error"] is None


def test_validate_invalid_url():
    """Test invalid URL validation."""
    result = validate_url("not-a-url")
    assert result["valid"] is False
    assert result["type"] == "invalid"
    assert result["error"] is not None


def test_validate_empty_url():
    """Test empty URL validation."""
    result = validate_url("")
    assert result["valid"] is False
    assert result["type"] == "invalid"
    assert result["error"] == "URL cannot be empty"

