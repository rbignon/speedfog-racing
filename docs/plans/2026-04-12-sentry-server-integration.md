# Sentry Server Integration

**Date**: 2026-04-12
**Scope**: Backend only (server/)
**Goal**: Post-mortem debugging of races, filterable by `race_id` in Sentry

## Sentry.io Setup Procedure

1. Create an account on sentry.io (free Developer plan: 5k errors/month, 1 member)
2. Create an organization (e.g. `speedfog`)
3. Create a project of type **Python / FastAPI**, named `speedfog-server`
4. Retrieve the DSN from Project Settings > Client Keys (DSN)
   - Format: `https://<key>@o<org_id>.ingest.sentry.io/<project_id>`
5. Add the DSN to the server `.env` file as `SENTRY_DSN=<dsn>`
6. Configure alerts: Alerts > Create Alert Rule > "Issue Alert", notify by email
   on each new error. Optionally filter by tag `race_id`.

## Design

### 1. Dependency

Add `sentry-sdk[fastapi]` to `pyproject.toml` dependencies. The `fastapi` extra
enables automatic FastAPI, Starlette, and asyncio integrations.

### 2. Configuration

Add two settings to `config.py`:

- `sentry_dsn: str = ""` - empty disables Sentry (local dev, tests)
- `sentry_environment: str = "production"` - to distinguish staging/prod later

### 3. SDK Initialization

In `main.py`, before the FastAPI app creation, conditionally initialize Sentry:

```python
import sentry_sdk

if settings.sentry_dsn:
    sentry_sdk.init(
        dsn=settings.sentry_dsn,
        environment=settings.sentry_environment,
        release=__version__,
        traces_sample_rate=0,  # no performance monitoring for now
    )
```

The SDK auto-configures with the FastAPI integration: it captures unhandled
exceptions in HTTP endpoints and attaches method/URL/status as context.

No changes to existing middleware stack (CORS, SlowAPI).

### 4. WebSocket Instrumentation

The Sentry SDK does not auto-capture WebSocket errors. We instrument the
base handler classes; concrete subclasses (RaceModHandler, TrainingModHandler,
etc.) require **zero changes**.

#### 4a. Exception capture in `BaseHandler.run()`

Add `sentry_sdk.capture_exception()` in the existing `except Exception` block:

```python
except Exception:
    logger.exception("%s error: %s", type(self).__name__, self.entity_id)
    sentry_sdk.capture_exception()
```

#### 4b. Sentry scope via `_configure_sentry_scope()` hook

New method called in `run()` right after `_initialize()` succeeds:

```python
def _configure_sentry_scope(self) -> None:
    sentry_sdk.set_tag("entity_id", str(self.entity_id))
    sentry_sdk.set_tag("handler", type(self).__name__)
```

`BaseModHandler` overrides to enrich with participant context:

```python
def _configure_sentry_scope(self) -> None:
    super()._configure_sentry_scope()
    sentry_sdk.set_tag("participant_id", str(self._entity_db_id))
    sentry_sdk.set_user({"username": self._username})
```

#### 4c. Opt-in breadcrumbs via `@sentry_breadcrumb` decorator

To avoid quota explosion from high-frequency messages (status_update fires
every second), breadcrumbs are opt-in per handler method:

```python
def sentry_breadcrumb(func):
    """Mark a WebSocket message handler as generating a Sentry breadcrumb."""
    func._sentry_breadcrumb = True
    return func
```

In `_handle_message`, check the flag before adding a breadcrumb:

```python
async def _handle_message(self, msg: dict[str, Any]) -> None:
    msg_type = msg.get("type")
    handler = self._message_handlers.get(msg_type)
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

Decorated handlers in `BaseModHandler`:

- `_handle_event_flag` - zone transitions (important for debugging)
- `_handle_zone_query` - loading screen position queries

Not decorated (too frequent, low debugging value):

- `_handle_status_update` - IGT/death count, fires every second

### 5. REST Endpoint Context

Use a FastAPI dependency to tag `race_id` on API routes that have it:

```python
async def sentry_race_context(race_id: uuid.UUID) -> None:
    sentry_sdk.set_tag("race_id", str(race_id))
```

Injected via `Depends(sentry_race_context)` on race-related routes in
`api/races.py`.

For WebSocket endpoints in `main.py`, tag before delegating to the handler:

```python
@app.websocket("/ws/mod/{race_id}")
async def websocket_mod(websocket: WebSocket, race_id: uuid.UUID) -> None:
    sentry_sdk.set_tag("race_id", str(race_id))
    await handle_mod_websocket(websocket, race_id, async_session_maker)
```

### 6. Tests

- Existing tests run with `sentry_dsn = ""` (default), so Sentry is never
  initialized during tests. No test changes needed.
- Verify this by running the full test suite after integration.

## Files Changed Summary

| File                   | Change                                                                                                                       |
| ---------------------- | ---------------------------------------------------------------------------------------------------------------------------- |
| `pyproject.toml`       | Add `sentry-sdk[fastapi]` dependency                                                                                         |
| `config.py`            | Add `sentry_dsn`, `sentry_environment` settings                                                                              |
| `main.py`              | Add conditional `sentry_sdk.init()`, tag race_id on WS endpoints                                                             |
| `websocket/handler.py` | Add `sentry_breadcrumb` decorator, `_configure_sentry_scope()`, `capture_exception()`, breadcrumb check in `_handle_message` |
| `api/races.py`         | Add `Depends(sentry_race_context)` on race routes                                                                            |

## What Does Not Change

- Business logic, race lifecycle, zone tracking
- WebSocket handler subclasses (RaceModHandler, TrainingModHandler, etc.)
- Middleware stack (CORS, SlowAPI)
- Error response format
- Frontend (deferred to a later iteration)
