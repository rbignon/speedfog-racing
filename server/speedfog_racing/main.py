"""SpeedFog Racing - FastAPI Application."""

import argparse
import asyncio
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from pathlib import Path

import sentry_sdk
from fastapi import FastAPI, Request, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from speedfog_racing import __version__
from speedfog_racing.api import api_router
from speedfog_racing.config import settings
from speedfog_racing.database import async_session_maker
from speedfog_racing.rate_limit import limiter
from speedfog_racing.services.chat_cleanup import chat_cleanup_loop
from speedfog_racing.services.daily_seed_loop import daily_seed_loop
from speedfog_racing.services.hard_close_loop import hard_close_loop
from speedfog_racing.services.i18n import load_translations
from speedfog_racing.services.inactivity_monitor import inactivity_monitor_loop
from speedfog_racing.services.twitch_live import twitch_live_poll_loop
from speedfog_racing.websocket import (
    handle_mod_websocket,
    handle_spectator_websocket,
    handle_training_mod_websocket,
    handle_training_spectator_websocket,
)
from speedfog_racing.websocket.race.manager import manager as ws_manager

# Configure logging
logging.basicConfig(
    level=getattr(logging, settings.log_level),
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=__version__,
        traces_sample_rate=0,
        enable_logs=True,
    )


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Application lifespan: startup and shutdown."""
    # Startup
    logger.info("Starting SpeedFog Racing server...")

    # Load i18n translations
    try:
        i18n_dir = Path(settings.i18n_dir)
        if not i18n_dir.is_absolute():
            i18n_dir = Path(__file__).resolve().parent.parent / i18n_dir
        translations = load_translations(i18n_dir)
        logger.info("Loaded %d translation locale(s)", len(translations))
    except Exception as e:
        logger.warning(f"i18n loading failed: {e}")

    # Start inactivity monitor
    monitor_task = asyncio.create_task(inactivity_monitor_loop(async_session_maker))

    # Start hard-close monitor (finalizes races past started_at + race_duration_minutes)
    hard_close_task = asyncio.create_task(hard_close_loop(async_session_maker))

    # Start daily seed creation loop (one Daily Seed race per UTC day at 08:00).
    daily_seed_task = asyncio.create_task(daily_seed_loop(async_session_maker))

    # Start Twitch live polling (only if Twitch credentials are configured)
    twitch_live_task = None
    if settings.twitch_client_id and settings.twitch_client_secret:
        twitch_live_task = asyncio.create_task(
            twitch_live_poll_loop(async_session_maker, ws_manager=ws_manager)
        )

    # Start chat cleanup background task
    chat_cleanup_task = asyncio.create_task(chat_cleanup_loop(async_session_maker))

    yield

    # Shutdown
    chat_cleanup_task.cancel()
    try:
        await chat_cleanup_task
    except asyncio.CancelledError:
        pass
    if twitch_live_task:
        twitch_live_task.cancel()
        try:
            await twitch_live_task
        except asyncio.CancelledError:
            pass
    monitor_task.cancel()
    try:
        await monitor_task
    except asyncio.CancelledError:
        pass
    hard_close_task.cancel()
    try:
        await hard_close_task
    except asyncio.CancelledError:
        pass
    daily_seed_task.cancel()
    try:
        await daily_seed_task
    except asyncio.CancelledError:
        pass
    logger.info("Shutting down SpeedFog Racing server...")


app = FastAPI(
    title="SpeedFog Racing API",
    description="Competitive racing platform for SpeedFog",
    version=__version__,
    lifespan=lifespan,
)

# Store limiter on app state for slowapi
app.state.limiter = limiter


def _rate_limit_exceeded_handler(request: Request, exc: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(
        status_code=429,
        content={"detail": "Rate limit exceeded. Please try again later."},
    )


app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)  # type: ignore[arg-type]
app.add_middleware(SlowAPIMiddleware)


# Default /api/* responses to Cache-Control: no-store. Without this, browsers
# may heuristically cache successful 200s and, more importantly, status codes
# considered cacheable by RFC 7231 (e.g. 404, 410), causing stale errors to
# stick until the user does a hard reload. Endpoints that legitimately want to
# be cached (e.g. OG image/meta routes) opt out by setting their own
# Cache-Control header on the response; setdefault preserves that.
@app.middleware("http")
async def no_store_api_responses(request: Request, call_next: RequestResponseEndpoint) -> Response:
    response = await call_next(request)
    if request.url.path.startswith("/api/"):
        response.headers.setdefault("Cache-Control", "no-store")
    return response


# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE"],
    allow_headers=["Authorization", "Content-Type"],
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
    sentry_sdk.set_tag("race_id", str(race_id))
    await handle_mod_websocket(websocket, race_id, async_session_maker)


@app.websocket("/ws/race/{race_id}")
async def websocket_spectator(websocket: WebSocket, race_id: uuid.UUID) -> None:
    """WebSocket endpoint for spectator connections."""
    sentry_sdk.set_tag("race_id", str(race_id))
    await handle_spectator_websocket(websocket, race_id, async_session_maker)


@app.websocket("/ws/training/{session_id}")
async def websocket_training_mod(websocket: WebSocket, session_id: uuid.UUID) -> None:
    """WebSocket endpoint for training mod connections."""
    await handle_training_mod_websocket(websocket, session_id, async_session_maker)


@app.websocket("/ws/training/{session_id}/spectate")
async def websocket_training_spectator(websocket: WebSocket, session_id: uuid.UUID) -> None:
    """WebSocket endpoint for training spectator connections."""
    await handle_training_spectator_websocket(websocket, session_id, async_session_maker)


def main() -> None:
    """Run the server."""
    import uvicorn

    parser = argparse.ArgumentParser(description="SpeedFog Racing Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to")
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
