# Sentry Server Integration - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add Sentry error tracking to the FastAPI backend, with `race_id` context on all race-related errors and WebSocket breadcrumbs for post-mortem debugging.

**Architecture:** `sentry-sdk[fastapi]` auto-captures HTTP exceptions. WebSocket instrumentation goes in BaseHandler/BaseModHandler (the abstraction layer), so subclasses need zero changes. A `@sentry_breadcrumb` decorator opts in specific message handlers. A FastAPI dependency tags `race_id` on REST routes.

**Tech Stack:** sentry-sdk[fastapi], Python 3.11, FastAPI, asyncio

**Spec:** `docs/plans/2026-04-12-sentry-server-integration.md`

---

## Tasks

### Task 1: Add sentry-sdk dependency and config settings

**Files:**

- Modify: `server/pyproject.toml:6-21`
- Modify: `server/speedfog_racing/config.py:6-52`

- [ ] **Step 1: Add sentry-sdk[fastapi] to pyproject.toml**

In `server/pyproject.toml`, add to the `dependencies` list:

```toml
    "sentry-sdk[fastapi]>=2.0",
```

- [ ] **Step 2: Add Sentry settings to config.py**

In `server/speedfog_racing/config.py`, add two fields to the `Settings` class, in a new `# Sentry` section after the `# Server` section (before line 51):

```python
    # Sentry
    sentry_dsn: str = ""
    sentry_environment: str = "production"
```

- [ ] **Step 3: Install dependencies**

Run: `cd server && uv sync --all-extras`
Expected: successful install including sentry-sdk

- [ ] **Step 4: Run existing tests to confirm no breakage**

Run: `cd server && uv run pytest -x -q`
Expected: all tests pass (sentry_dsn defaults to "", Sentry stays disabled)

- [ ] **Step 5: Commit**

```bash
git add server/pyproject.toml server/speedfog_racing/config.py server/uv.lock
git commit -m "feat: add sentry-sdk dependency and config settings"
```

---

### Task 2: Initialize Sentry SDK in main.py

**Files:**

- Modify: `server/speedfog_racing/main.py:1-40`

- [ ] **Step 1: Add Sentry init before app creation**

In `server/speedfog_racing/main.py`, add the import at the top (after line 9, with the other stdlib imports):

```python
import sentry_sdk
```

Then, after the logging setup (after line 39, before the lifespan function), add:

```python
if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=__version__,
        traces_sample_rate=0,
    )
```

- [ ] **Step 2: Tag race_id on WebSocket endpoints**

In `server/speedfog_racing/main.py`, add `sentry_sdk.set_tag` calls at the start of each race WebSocket endpoint (lines 141-151):

```python
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
```

Training endpoints (`/ws/training/...`) don't need the tag since the goal is race debugging.

- [ ] **Step 3: Run tests**

Run: `cd server && uv run pytest -x -q`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add server/speedfog_racing/main.py
git commit -m "feat: initialize Sentry SDK conditionally in main.py"
```

---

### Task 3: Instrument BaseHandler with Sentry scope and exception capture

**Files:**

- Modify: `server/speedfog_racing/websocket/handler.py:1-362`

- [ ] **Step 1: Add sentry_sdk import**

In `server/speedfog_racing/websocket/handler.py`, add after line 9 (`import time`):

```python
from collections.abc import Callable
from functools import wraps
```

Wait, `Callable` is already imported on line 13. Add `sentry_sdk` import after line 8 (`import json`):

```python
import sentry_sdk
```

- [ ] **Step 2: Add the `sentry_breadcrumb` decorator**

After the `SHARED_ENTRANCE_DEDUP_MS` constant (line 50), add:

```python


def sentry_breadcrumb(func: Callable[..., Any]) -> Callable[..., Any]:
    """Mark a WebSocket message handler as generating a Sentry breadcrumb."""
    func._sentry_breadcrumb = True  # type: ignore[attr-defined]
    return func
```

- [ ] **Step 3: Add `_configure_sentry_scope()` to BaseHandler**

In the `BaseHandler` class, add a new method after `_cleanup` (after line 361):

```python
    def _configure_sentry_scope(self) -> None:
        """Set Sentry tags for this connection. Override to enrich."""
        sentry_sdk.set_tag("entity_id", str(self.entity_id))
        sentry_sdk.set_tag("handler", type(self).__name__)
```

- [ ] **Step 4: Wire scope and capture into `BaseHandler.run()`**

Modify the `run()` method (lines 310-331). Add `self._configure_sentry_scope()` after `self._connected = True`, and add `sentry_sdk.capture_exception()` in the `except Exception` block:

```python
    async def run(self) -> None:
        await self.websocket.accept()
        try:
            if not await self._initialize():
                return
            self._connected = True
            self._configure_sentry_scope()
            heartbeat_task = asyncio.create_task(heartbeat_loop(self.websocket))
            try:
                await self._message_loop()
            finally:
                heartbeat_task.cancel()
                try:
                    await heartbeat_task
                except asyncio.CancelledError:
                    pass
        except WebSocketDisconnect:
            logger.info("%s disconnected: %s", type(self).__name__, self.entity_id)
        except Exception:
            logger.exception("%s error: %s", type(self).__name__, self.entity_id)
            sentry_sdk.capture_exception()
        finally:
            if self._connected:
                await self._cleanup()
```

Two additions: `self._configure_sentry_scope()` on line after `self._connected = True`, and `sentry_sdk.capture_exception()` after `logger.exception(...)`.

- [ ] **Step 5: Add breadcrumb check in `_handle_message()`**

Modify `_handle_message()` (lines 349-355) to check the decorator flag:

```python
    async def _handle_message(self, msg: dict[str, Any]) -> None:
        msg_type = msg.get("type")
        handler = self._message_handlers.get(msg_type)  # type: ignore[arg-type]
        if handler:
            if getattr(handler, "_sentry_breadcrumb", False):
                sentry_sdk.add_breadcrumb(
                    category="websocket",
                    message=f"Received: {msg_type}",
                    level="info",
                )
            await handler(msg)
        else:
            logger.warning("%s: unknown message type: %s", type(self).__name__, msg_type)
```

- [ ] **Step 6: Run tests**

Run: `cd server && uv run pytest -x -q`
Expected: all tests pass

- [ ] **Step 7: Commit**

```bash
git add server/speedfog_racing/websocket/handler.py
git commit -m "feat: add Sentry scope, capture, and breadcrumb support in BaseHandler"
```

---

### Task 4: Enrich Sentry context in BaseModHandler and decorate handlers

**Files:**

- Modify: `server/speedfog_racing/websocket/handler.py:367-900`

- [ ] **Step 1: Override `_configure_sentry_scope()` in BaseModHandler**

The concrete subclasses (RaceModHandler, TrainingModHandler) store participant/user info in different attributes set during `_authenticate`. We need a hook that works for both. Add the override in `BaseModHandler`, after the `_cleanup` method (after line 396):

```python
    def _configure_sentry_scope(self) -> None:
        super()._configure_sentry_scope()
        sentry_sdk.set_tag("connection_type", "mod")
```

This provides a base enrichment. The concrete subclasses store user/participant data in their own attributes (`_participant_id`, `_user_id`), but since we tagged `entity_id` (which is the race_id or session_id) in BaseHandler, and `race_id` at the WebSocket endpoint level, we already have the key context for filtering.

- [ ] **Step 2: Decorate `_handle_event_flag` with `@sentry_breadcrumb`**

On line 570, add the decorator:

```python
    @sentry_breadcrumb
    async def _handle_event_flag(self, msg: dict[str, Any]) -> None:
```

- [ ] **Step 3: Decorate `_handle_zone_query` with `@sentry_breadcrumb`**

On line 690, add the decorator:

```python
    @sentry_breadcrumb
    async def _handle_zone_query(self, msg: dict[str, Any]) -> None:
```

`_handle_status_update` (line 497) is intentionally NOT decorated (fires every second, low debugging value).

- [ ] **Step 4: Run type checker**

Run: `cd server && uv run mypy speedfog_racing/`
Expected: no new errors

- [ ] **Step 5: Run tests**

Run: `cd server && uv run pytest -x -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add server/speedfog_racing/websocket/handler.py
git commit -m "feat: enrich Sentry context in BaseModHandler, decorate event_flag and zone_query"
```

---

### Task 5: Add race_id tagging on REST endpoints

**Files:**

- Modify: `server/speedfog_racing/api/races.py:1-75`

- [ ] **Step 1: Add the sentry_race_context dependency**

In `server/speedfog_racing/api/races.py`, add the import after line 4 (`from pathlib import Path`):

```python
import sentry_sdk
```

Then, after the existing imports block (after line 75), add:

```python

async def sentry_race_context(race_id: UUID) -> None:
    """FastAPI dependency: tag the current Sentry scope with race_id."""
    sentry_sdk.set_tag("race_id", str(race_id))
```

- [ ] **Step 2: Inject the dependency on all `{race_id}` routes**

Add `_sentry: None = Depends(sentry_race_context)` to every route that has a `race_id` parameter. The routes are (16 total):

- `get_race` (line 480)
- `update_race` (line 493)
- `add_participant` (line 606)
- `remove_participant` (line 741)
- `delete_invite` (line 784)
- `leave_race` (line 1032)
- `cast_join` (line 1087)
- `cast_leave` (line 1137)
- `start_race` (line 1170)
- `reroll_seed` (line 1253)
- `release_seeds` (line 1327)
- `reset_race` (line 1383)
- `finish_race` (line 1427)
- `abandon_race` (line 1486)
- `delete_race` (line 1562)
- `get_my_seed_pack` (line 1602)

For each, add the dependency parameter. Example for `get_race`:

```python
async def get_race(
    race_id: UUID,
    db: AsyncSession = Depends(get_db),
    user: User | None = Depends(get_current_user_optional),
    _sentry: None = Depends(sentry_race_context),
) -> RaceDetailResponse:
```

- [ ] **Step 3: Run linter**

Run: `cd server && uv run ruff check speedfog_racing/api/races.py`
Expected: no errors

- [ ] **Step 4: Run type checker**

Run: `cd server && uv run mypy speedfog_racing/`
Expected: no new errors

- [ ] **Step 5: Run tests**

Run: `cd server && uv run pytest -x -q`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add server/speedfog_racing/api/races.py
git commit -m "feat: tag race_id in Sentry scope on all race REST endpoints"
```

---

### Task 6: Final verification

**Files:** None (verification only)

- [ ] **Step 1: Run full test suite**

Run: `cd server && uv run pytest -v`
Expected: all tests pass, no Sentry-related warnings

- [ ] **Step 2: Run linter and type checker**

Run: `cd server && uv run ruff check . && uv run mypy speedfog_racing/`
Expected: clean

- [ ] **Step 3: Start dev server and verify health**

Run: `cd server && uv run speedfog-racing --host 127.0.0.1 --port 8000`
Expected: server starts without errors, no Sentry init message (DSN not set in dev .env)

Hit `http://localhost:8000/health` to confirm it responds `{"status": "ok"}`.

- [ ] **Step 4: Verify Sentry init with DSN (manual)**

Temporarily set `SENTRY_DSN=<your-dsn>` in `server/.env`, restart the server, and trigger an error (e.g. hit a non-existent race endpoint). Verify the error appears in Sentry with the expected tags. Remove the DSN from `.env` after testing.
