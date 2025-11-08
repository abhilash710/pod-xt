"""Preset management for PodX Studio."""

import json
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, asdict

from ..logging import get_logger

logger = get_logger(__name__)


@dataclass
class Preset:
    """Preset configuration."""
    name: str
    config: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {"name": self.name, "config": self.config}


class PresetManager:
    """Manages presets stored in ~/.podx/ui/presets.json."""
    
    def __init__(self, presets_file: Optional[Path] = None):
        """Initialize preset manager.
        
        Args:
            presets_file: Path to presets file (defaults to ~/.podx/ui/presets.json)
        """
        if presets_file is None:
            presets_dir = Path.home() / ".podx" / "ui"
            presets_dir.mkdir(parents=True, exist_ok=True)
            presets_file = presets_dir / "presets.json"
        
        self.presets_file = presets_file
        self._ensure_default_preset()
    
    def _ensure_default_preset(self) -> None:
        """Ensure default 'Recommended' preset exists."""
        presets = self.list_presets()
        if not any(p.name == "Recommended" for p in presets):
            self.create_preset("Recommended", {
                "diarize": True,
                "deepcast": True,
                "extract_markdown": True,
                "preprocess": True,
            })
    
    def _load_presets(self) -> Dict[str, Dict[str, Any]]:
        """Load presets from file."""
        if not self.presets_file.exists():
            return {}
        
        try:
            content = self.presets_file.read_text()
            data = json.loads(content)
            return data if isinstance(data, dict) else {}
        except Exception as e:
            logger.warning("Failed to load presets", error=str(e))
            return {}
    
    def _save_presets(self, presets: Dict[str, Dict[str, Any]]) -> None:
        """Save presets to file."""
        self.presets_file.parent.mkdir(parents=True, exist_ok=True)
        self.presets_file.write_text(json.dumps(presets, indent=2))
    
    def list_presets(self) -> List[Preset]:
        """List all presets.
        
        Returns:
            List of Preset objects
        """
        presets_dict = self._load_presets()
        return [
            Preset(name=name, config=config)
            for name, config in presets_dict.items()
        ]
    
    def get_preset(self, name: str) -> Optional[Preset]:
        """Get a preset by name.
        
        Args:
            name: Preset name
            
        Returns:
            Preset object or None if not found
        """
        presets_dict = self._load_presets()
        if name not in presets_dict:
            return None
        
        return Preset(name=name, config=presets_dict[name])
    
    def create_preset(self, name: str, config: Dict[str, Any]) -> Preset:
        """Create a new preset.
        
        Args:
            name: Preset name
            config: Preset configuration dictionary
            
        Returns:
            Created Preset object
            
        Raises:
            ValueError: If preset already exists
        """
        presets_dict = self._load_presets()
        if name in presets_dict:
            raise ValueError(f"Preset '{name}' already exists")
        
        presets_dict[name] = config
        self._save_presets(presets_dict)
        logger.info("Created preset", name=name)
        return Preset(name=name, config=config)
    
    def update_preset(self, name: str, config: Dict[str, Any]) -> Preset:
        """Update an existing preset.
        
        Args:
            name: Preset name
            config: Updated configuration dictionary
            
        Returns:
            Updated Preset object
            
        Raises:
            ValueError: If preset doesn't exist
        """
        presets_dict = self._load_presets()
        if name not in presets_dict:
            raise ValueError(f"Preset '{name}' does not exist")
        
        presets_dict[name] = config
        self._save_presets(presets_dict)
        logger.info("Updated preset", name=name)
        return Preset(name=name, config=config)
    
    def delete_preset(self, name: str) -> bool:
        """Delete a preset.
        
        Args:
            name: Preset name
            
        Returns:
            True if deleted, False if not found
        """
        presets_dict = self._load_presets()
        if name not in presets_dict:
            return False
        
        # Don't allow deleting the default Recommended preset
        if name == "Recommended":
            raise ValueError("Cannot delete the default 'Recommended' preset")
        
        del presets_dict[name]
        self._save_presets(presets_dict)
        logger.info("Deleted preset", name=name)
        return True

