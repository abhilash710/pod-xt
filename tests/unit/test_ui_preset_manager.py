"""Unit tests for PodX Studio preset manager."""

import pytest
import tempfile
from pathlib import Path
from podx.ui.preset_manager import PresetManager, Preset


def test_create_preset():
    """Test creating a preset."""
    with tempfile.TemporaryDirectory() as tmpdir:
        presets_file = Path(tmpdir) / "presets.json"
        manager = PresetManager(presets_file=presets_file)
        
        preset = manager.create_preset("Test Preset", {"diarize": True, "deepcast": False})
        assert preset.name == "Test Preset"
        assert preset.config == {"diarize": True, "deepcast": False}


def test_list_presets():
    """Test listing presets."""
    with tempfile.TemporaryDirectory() as tmpdir:
        presets_file = Path(tmpdir) / "presets.json"
        manager = PresetManager(presets_file=presets_file)
        
        manager.create_preset("Preset 1", {"diarize": True})
        manager.create_preset("Preset 2", {"deepcast": True})
        
        presets = manager.list_presets()
        assert len(presets) >= 2  # At least 2, plus default Recommended
        names = [p.name for p in presets]
        assert "Preset 1" in names
        assert "Preset 2" in names


def test_get_preset():
    """Test getting a preset."""
    with tempfile.TemporaryDirectory() as tmpdir:
        presets_file = Path(tmpdir) / "presets.json"
        manager = PresetManager(presets_file=presets_file)
        
        manager.create_preset("Test Preset", {"diarize": True})
        
        preset = manager.get_preset("Test Preset")
        assert preset is not None
        assert preset.name == "Test Preset"
        assert preset.config == {"diarize": True}
        
        assert manager.get_preset("Non-existent") is None


def test_delete_preset():
    """Test deleting a preset."""
    with tempfile.TemporaryDirectory() as tmpdir:
        presets_file = Path(tmpdir) / "presets.json"
        manager = PresetManager(presets_file=presets_file)
        
        manager.create_preset("Test Preset", {"diarize": True})
        assert manager.get_preset("Test Preset") is not None
        
        success = manager.delete_preset("Test Preset")
        assert success is True
        assert manager.get_preset("Test Preset") is None


def test_cannot_delete_recommended():
    """Test that Recommended preset cannot be deleted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        presets_file = Path(tmpdir) / "presets.json"
        manager = PresetManager(presets_file=presets_file)
        
        with pytest.raises(ValueError, match="Cannot delete"):
            manager.delete_preset("Recommended")

