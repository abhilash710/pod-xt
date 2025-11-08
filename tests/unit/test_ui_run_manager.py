"""Unit tests for PodX Studio run manager."""

import pytest
import tempfile
from pathlib import Path
from podx.ui.run_manager import RunManager, RunState
from podx.domain import PipelineConfig, PipelineResult


def test_create_run():
    """Test creating a run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.json"
        manager = RunManager(history_file=history_file, max_concurrent=1)
        
        config = PipelineConfig(show="Test Podcast", diarize=True)
        run_id = manager.create_run(config)
        
        assert run_id is not None
        run = manager.get_run(run_id)
        assert run is not None
        assert run.status == "pending"
        assert run.config.show == "Test Podcast"


def test_update_run_status():
    """Test updating run status."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.json"
        manager = RunManager(history_file=history_file)
        
        config = PipelineConfig(show="Test Podcast")
        run_id = manager.create_run(config)
        
        manager.update_run_status(run_id, "running")
        run = manager.get_run(run_id)
        assert run.status == "running"


def test_update_run_progress():
    """Test updating run progress."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.json"
        manager = RunManager(history_file=history_file)
        
        config = PipelineConfig(show="Test Podcast")
        run_id = manager.create_run(config)
        
        manager.update_run_progress(run_id, "fetch", "completed")
        run = manager.get_run(run_id)
        assert run.progress["fetch"] == "completed"


def test_set_run_result():
    """Test setting run result."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.json"
        manager = RunManager(history_file=history_file)
        
        config = PipelineConfig(show="Test Podcast")
        run_id = manager.create_run(config)
        
        result = PipelineResult(
            workdir=Path(tmpdir),
            steps_completed=["fetch", "transcribe"],
            artifacts={"transcript": str(Path(tmpdir) / "transcript.json")},
            duration=10.5
        )
        
        manager.set_run_result(run_id, result)
        run = manager.get_run(run_id)
        assert run.status == "completed"
        assert run.result is not None
        assert run.result.duration == 10.5


def test_cancel_run():
    """Test canceling a run."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.json"
        manager = RunManager(history_file=history_file)
        
        config = PipelineConfig(show="Test Podcast")
        run_id = manager.create_run(config)
        manager.update_run_status(run_id, "running")
        
        success = manager.cancel_run(run_id)
        assert success is True
        
        run = manager.get_run(run_id)
        assert run.status == "canceled"


def test_concurrency_limit():
    """Test concurrency limit enforcement."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.json"
        manager = RunManager(history_file=history_file, max_concurrent=1)
        
        config = PipelineConfig(show="Test Podcast")
        run_id1 = manager.create_run(config)
        manager.update_run_status(run_id1, "running")
        
        # Should fail to create second run
        with pytest.raises(RuntimeError, match="Maximum concurrent runs"):
            manager.create_run(config)


def test_list_recent_runs():
    """Test listing recent runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        history_file = Path(tmpdir) / "history.json"
        manager = RunManager(history_file=history_file)
        
        config = PipelineConfig(show="Test Podcast")
        run_id1 = manager.create_run(config)
        run_id2 = manager.create_run(config)
        
        runs = manager.list_recent_runs()
        assert len(runs) >= 2
        run_ids = [r.run_id for r in runs]
        assert run_id1 in run_ids
        assert run_id2 in run_ids

