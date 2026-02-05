"""SpeedFog Racing - FastAPI Application."""

import argparse
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware

from speedfog_racing import __version__
from speedfog_racing.api import api_router
from speedfog_racing.config import settings
from speedfog_racing.database import async_session_maker, get_db_context, init_db
from speedfog_racing.services import scan_pool
from speedfog_racing.websocket import handle_mod_websocket, handle_spectator_websocket

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    # Startup
    logger.info("Starting SpeedFog Racing server...")
    try:
        await init_db()
        logger.info("Database initialized")
    except Exception as e:
        logger.warning(f"Database initialization skipped: {e}")

    # Scan seed pool
    try:
        async with get_db_context() as db:
            added = await scan_pool(db, "standard")
            logger.info(f"Seed pool scanned: {added} new seeds added")
    except Exception as e:
        logger.warning(f"Seed pool scan failed: {e}")

    yield

    # Shutdown
    logger.info("Shutting down SpeedFog Racing server...")


app = FastAPI(
    title="SpeedFog Racing API",
    description="Competitive racing platform for SpeedFog",
    version=__version__,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount API routes
app.include_router(api_router, prefix="/api")


@app.get("/health")
async def health_check() -> dict[str, str]:
    """Health check endpoint."""
    return {"status": "ok", "version": __version__}


# WebSocket routes


@app.websocket("/ws/mod/{race_id}")
async def websocket_mod(websocket: WebSocket, race_id: uuid.UUID) -> None:
    """WebSocket endpoint for mod connections."""
    async with async_session_maker() as db:
        await handle_mod_websocket(websocket, race_id, db)


@app.websocket("/ws/race/{race_id}")
async def websocket_spectator(websocket: WebSocket, race_id: uuid.UUID) -> None:
    """WebSocket endpoint for spectator connections."""
    async with async_session_maker() as db:
        await handle_spectator_websocket(websocket, race_id, db)


def main() -> None:
    """Run the server."""
    import uvicorn

    parser = argparse.ArgumentParser(description="SpeedFog Racing Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to")
    parser.add_argument("--port", type=int, default=8000, help="Port to listen on")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    args = parser.parse_args()

    logger.info(f"Starting server on http://{args.host}:{args.port}")
    logger.info(f"API docs: http://localhost:{args.port}/docs")

    uvicorn.run(
        "speedfog_racing.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()
