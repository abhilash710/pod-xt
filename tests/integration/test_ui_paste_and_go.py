"""E2E test for PodX Studio Paste-and-Go workflow."""

import pytest
import asyncio
from pathlib import Path
import tempfile


@pytest.mark.asyncio
async def test_paste_and_go_workflow():
    """Test the Paste-and-Go workflow: start server, submit URL, verify progress."""
    # This is a placeholder test - full implementation would:
    # 1. Start the FastAPI server in a background process
    # 2. Make HTTP request to /api/runs with a test URL
    # 3. Connect WebSocket and verify progress updates
    # 4. Poll /api/runs/{run_id} until completion
    # 5. Verify artifacts are created
    
    # For now, just verify the API endpoints exist
    from podx.ui.api import router
    
    # Check that routes are registered
    routes = [r.path for r in router.routes]
    assert "/api/runs" in routes
    assert "/api/runs/{run_id}" in routes
    assert "/health" in routes

