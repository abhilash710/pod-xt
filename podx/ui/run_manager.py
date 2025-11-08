"""Run management for PodX Studio."""

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Optional, List, Callable, Any
from dataclasses import dataclass, asdict, field

from ..domain import PipelineConfig, PipelineResult
from ..logging import get_logger

logger = get_logger(__name__)


@dataclass
class RunState:
    """State of a pipeline run."""
    run_id: str
    config: PipelineConfig
    status: str  # pending, running, completed, failed, canceled
    progress: Dict[str, str] = field(default_factory=dict)  # stage -> status
    result: Optional[PipelineResult] = None
    error: Optional[str] = None
    started_at: datetime = field(default_factory=datetime.now)
    completed_at: Optional[datetime] = None
    notion_url: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "run_id": self.run_id,
            "config": self._config_to_dict(),
            "status": self.status,
            "progress": self.progress,
            "result": self._result_to_dict() if self.result else None,
            "error": self.error,
            "started_at": self.started_at.isoformat(),
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "notion_url": self.notion_url,
        }
    
    def _config_to_dict(self) -> Dict[str, Any]:
        """Convert PipelineConfig to dict."""
        config_dict = {}
        for key, value in asdict(self.config).items():
            if isinstance(value, Path):
                config_dict[key] = str(value)
            else:
                config_dict[key] = value
        return config_dict
    
    def _result_to_dict(self) -> Dict[str, Any]:
        """Convert PipelineResult to dict."""
        if not self.result:
            return {}
        return {
            "workdir": str(self.result.workdir),
            "steps_completed": self.result.steps_completed,
            "artifacts": self.result.artifacts,
            "duration": self.result.duration,
            "errors": self.result.errors,
        }


class RunManager:
    """Manages active runs and run history."""
    
    def __init__(
        self,
        history_file: Optional[Path] = None,
        max_concurrent: int = 1,
        max_history: int = 20
    ):
        """Initialize run manager.
        
        Args:
            history_file: Path to history file (defaults to ~/.podx/ui/history.json)
            max_concurrent: Maximum number of concurrent runs (default: 1)
            max_history: Maximum number of runs to keep in history (default: 20)
        """
        if history_file is None:
            history_dir = Path.home() / ".podx" / "ui"
            history_dir.mkdir(parents=True, exist_ok=True)
            history_file = history_dir / "history.json"
        
        self.history_file = history_file
        self.max_concurrent = max_concurrent
        self.max_history = max_history
        self._active_runs: Dict[str, RunState] = {}
        self._run_tasks: Dict[str, Any] = {}  # run_id -> asyncio task
    
    def create_run(self, config: PipelineConfig) -> str:
        """Create a new run.
        
        Args:
            config: Pipeline configuration
            
        Returns:
            Run ID
            
        Raises:
            RuntimeError: If max concurrent runs reached
        """
        # Check concurrency limit
        active_count = sum(
            1 for run in self._active_runs.values()
            if run.status in ("pending", "running")
        )
        
        if active_count >= self.max_concurrent:
            raise RuntimeError(
                f"Maximum concurrent runs ({self.max_concurrent}) reached. "
                "Please wait for current runs to complete."
            )
        
        run_id = str(uuid.uuid4())
        run_state = RunState(
            run_id=run_id,
            config=config,
            status="pending",
            progress={}
        )
        
        self._active_runs[run_id] = run_state
        logger.info("Created run", run_id=run_id)
        return run_id
    
    def get_run(self, run_id: str) -> Optional[RunState]:
        """Get run state by ID.
        
        Args:
            run_id: Run ID
            
        Returns:
            RunState or None if not found
        """
        return self._active_runs.get(run_id)
    
    def update_run_status(self, run_id: str, status: str) -> None:
        """Update run status.
        
        Args:
            run_id: Run ID
            status: New status
        """
        run = self._active_runs.get(run_id)
        if run:
            run.status = status
            if status in ("completed", "failed", "canceled"):
                run.completed_at = datetime.now()
            logger.debug("Updated run status", run_id=run_id, status=status)
    
    def update_run_progress(self, run_id: str, stage: str, status: str) -> None:
        """Update progress for a specific stage.
        
        Args:
            run_id: Run ID
            stage: Stage name (e.g., "fetch", "transcribe")
            status: Stage status (e.g., "started", "completed", "failed")
        """
        run = self._active_runs.get(run_id)
        if run:
            run.progress[stage] = status
            logger.debug("Updated run progress", run_id=run_id, stage=stage, status=status)
    
    def set_run_result(self, run_id: str, result: PipelineResult) -> None:
        """Set run result.
        
        Args:
            run_id: Run ID
            result: Pipeline result
        """
        run = self._active_runs.get(run_id)
        if run:
            run.result = result
            run.status = "completed" if not result.errors else "failed"
            run.completed_at = datetime.now()
            logger.info("Set run result", run_id=run_id, success=not result.errors)
    
    def set_run_error(self, run_id: str, error: str) -> None:
        """Set run error.
        
        Args:
            run_id: Run ID
            error: Error message
        """
        run = self._active_runs.get(run_id)
        if run:
            run.error = error
            run.status = "failed"
            run.completed_at = datetime.now()
            logger.error("Set run error", run_id=run_id, error=error)
    
    def set_notion_url(self, run_id: str, notion_url: str) -> None:
        """Set Notion page URL for a run.
        
        Args:
            run_id: Run ID
            notion_url: Notion page URL
        """
        run = self._active_runs.get(run_id)
        if run:
            run.notion_url = notion_url
            logger.info("Set Notion URL", run_id=run_id)
    
    def cancel_run(self, run_id: str) -> bool:
        """Cancel an active run.
        
        Args:
            run_id: Run ID
            
        Returns:
            True if canceled, False if not found or not cancelable
        """
        run = self._active_runs.get(run_id)
        if not run:
            return False
        
        if run.status not in ("pending", "running"):
            return False
        
        run.status = "canceled"
        run.completed_at = datetime.now()
        
        # Cancel the task if it exists
        task = self._run_tasks.get(run_id)
        if task:
            task.cancel()
            del self._run_tasks[run_id]
        
        logger.info("Canceled run", run_id=run_id)
        return True
    
    def register_task(self, run_id: str, task: Any) -> None:
        """Register an asyncio task for a run.
        
        Args:
            run_id: Run ID
            task: Asyncio task
        """
        self._run_tasks[run_id] = task
    
    def list_recent_runs(self, limit: Optional[int] = None) -> List[RunState]:
        """List recent runs from history.
        
        Args:
            limit: Maximum number of runs to return (defaults to max_history)
            
        Returns:
            List of RunState objects, sorted by started_at descending
        """
        limit = limit or self.max_history
        
        # Combine active runs and history
        all_runs = list(self._active_runs.values())
        all_runs.extend(self._load_history())
        
        # Sort by started_at descending
        all_runs.sort(key=lambda r: r.started_at, reverse=True)
        
        # Deduplicate by run_id
        seen = set()
        unique_runs = []
        for run in all_runs:
            if run.run_id not in seen:
                seen.add(run.run_id)
                unique_runs.append(run)
        
        return unique_runs[:limit]
    
    def save_to_history(self, run: RunState) -> None:
        """Save a completed run to history.
        
        Args:
            run: RunState to save
        """
        history = self._load_history()
        
        # Remove if already exists
        history = [r for r in history if r.run_id != run.run_id]
        
        # Add to front
        history.insert(0, run)
        
        # Keep only max_history runs
        history = history[:self.max_history]
        
        self._save_history(history)
        logger.debug("Saved run to history", run_id=run.run_id)
    
    def _load_history(self) -> List[RunState]:
        """Load run history from file."""
        if not self.history_file.exists():
            return []
        
        try:
            content = self.history_file.read_text()
            data = json.loads(content)
            
            runs = []
            for run_dict in data:
                try:
                    run = self._dict_to_run_state(run_dict)
                    runs.append(run)
                except Exception as e:
                    logger.warning("Failed to load run from history", error=str(e))
                    continue
            
            return runs
        except Exception as e:
            logger.warning("Failed to load history", error=str(e))
            return []
    
    def _save_history(self, runs: List[RunState]) -> None:
        """Save run history to file."""
        self.history_file.parent.mkdir(parents=True, exist_ok=True)
        
        data = [run.to_dict() for run in runs]
        self.history_file.write_text(json.dumps(data, indent=2))
    
    def _dict_to_run_state(self, run_dict: Dict[str, Any]) -> RunState:
        """Convert dictionary to RunState."""
        # Convert config dict back to PipelineConfig
        config_dict = run_dict.get("config", {})
        config = PipelineConfig(**config_dict)
        
        # Convert result dict back to PipelineResult if present
        result = None
        if run_dict.get("result"):
            result_dict = run_dict["result"]
            result = PipelineResult(
                workdir=Path(result_dict["workdir"]),
                steps_completed=result_dict.get("steps_completed", []),
                artifacts=result_dict.get("artifacts", {}),
                duration=result_dict.get("duration", 0.0),
                errors=result_dict.get("errors", [])
            )
        
        # Parse datetime strings
        started_at = datetime.fromisoformat(run_dict["started_at"])
        completed_at = None
        if run_dict.get("completed_at"):
            completed_at = datetime.fromisoformat(run_dict["completed_at"])
        
        return RunState(
            run_id=run_dict["run_id"],
            config=config,
            status=run_dict["status"],
            progress=run_dict.get("progress", {}),
            result=result,
            error=run_dict.get("error"),
            started_at=started_at,
            completed_at=completed_at,
            notion_url=run_dict.get("notion_url")
        )

