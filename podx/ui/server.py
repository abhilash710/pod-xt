"""FastAPI server for PodX Studio."""

import os
import webbrowser
from pathlib import Path
from typing import Optional

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .api import router, init_managers
from ..config import get_config
from ..logging import get_logger

logger = get_logger(__name__)

app = FastAPI(title="PodX Studio", version="2.0.0")

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:8000", "http://127.0.0.1:8000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)

# Static files directory
static_dir = Path(__file__).parent / "static"


@app.on_event("startup")
async def startup_event():
    """Initialize managers on startup."""
    init_managers()
    logger.info("PodX Studio server started")


@app.get("/")
async def root():
    """Serve index.html."""
    index_path = static_dir / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    else:
        return {"message": "PodX Studio", "status": "Frontend not built. Run 'npm run build' in frontend directory."}


# Mount static files if directory exists
if static_dir.exists():
    app.mount("/assets", StaticFiles(directory=static_dir / "assets"), name="assets")
    # Serve other static files
    for file in static_dir.glob("*"):
        if file.is_file() and file.suffix in (".js", ".css", ".json", ".ico", ".png", ".svg"):
            @app.get(f"/{file.name}")
            async def serve_static(file_path: Path = file):
                return FileResponse(file_path)


def create_app() -> FastAPI:
    """Create and configure FastAPI app."""
    return app


def start_server(port: Optional[int] = None, open_browser: bool = True):
    """Start the FastAPI server.
    
    Args:
        port: Port to run on (defaults to config value)
        open_browser: Whether to open browser automatically
    """
    import uvicorn
    
    config = get_config()
    port = port or config.ui_port
    
    url = f"http://localhost:{port}"
    
    logger.info("Starting PodX Studio server", url=url, port=port)
    
    if open_browser:
        # Open browser after a short delay
        def open_browser_delayed():
            import time
            time.sleep(1)
            webbrowser.open(url)
        
        import threading
        threading.Thread(target=open_browser_delayed, daemon=True).start()
    
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="info")

