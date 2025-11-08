"""URL validation and type detection for PodX Studio."""

import re
from typing import Dict, Any
from urllib.parse import urlparse

from ..youtube import is_youtube_url
from ..errors import ValidationError


def validate_url(url: str) -> Dict[str, Any]:
    """Validate URL and detect its type.
    
    Args:
        url: URL string to validate
        
    Returns:
        Dictionary with:
        - valid: bool - Whether URL is valid
        - type: str - URL type: "youtube", "rss", "podcast_page", or "invalid"
        - error: Optional[str] - Error message if invalid
    """
    if not url or not url.strip():
        return {
            "valid": False,
            "type": "invalid",
            "error": "URL cannot be empty"
        }
    
    url = url.strip()
    
    # Check if it's a YouTube URL
    try:
        if is_youtube_url(url):
            return {
                "valid": True,
                "type": "youtube",
                "error": None
            }
    except Exception:
        pass
    
    # Check if it's a valid HTTP(S) URL
    try:
        parsed = urlparse(url)
        if not parsed.scheme or parsed.scheme not in ("http", "https"):
            return {
                "valid": False,
                "type": "invalid",
                "error": "URL must start with http:// or https://"
            }
        
        if not parsed.netloc:
            return {
                "valid": False,
                "type": "invalid",
                "error": "Invalid URL format"
            }
    except Exception as e:
        return {
            "valid": False,
            "type": "invalid",
            "error": f"Invalid URL format: {str(e)}"
        }
    
    # Check if it looks like an RSS feed
    # Common RSS indicators: .xml, /feed, /rss, /podcast, feed=, etc.
    rss_indicators = [
        r"\.xml$",
        r"/feed",
        r"/rss",
        r"/podcast",
        r"feed=",
        r"format=rss",
        r"type=rss"
    ]
    
    url_lower = url.lower()
    for pattern in rss_indicators:
        if re.search(pattern, url_lower):
            return {
                "valid": True,
                "type": "rss",
                "error": None
            }
    
    # Otherwise, assume it's a podcast page URL
    # (user will need to provide RSS URL or we'll try to find it)
    return {
        "valid": True,
        "type": "podcast_page",
        "error": None
    }

