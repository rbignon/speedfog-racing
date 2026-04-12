# Sentry Integration

Error tracking for post-mortem debugging of races. When something goes wrong
during a race (WebSocket disconnect, unhandled exception, zone tracking error),
the error is captured in Sentry with full context: `race_id`, `participant_id`,
user info, and a trail of recent WebSocket messages.

## Setup

### 1. Create the Sentry project

1. Sign up at [sentry.io](https://sentry.io) (the free Developer plan gives
   5k errors/month)
2. Create an organization (e.g. `speedfog`)
3. Create a project: platform **Python**, framework **FastAPI**, name
   `speedfog-server`
4. Copy the DSN from **Project Settings > Client Keys (DSN)**

### 2. Configure the server

Add the DSN to your `.env`:

```env
SENTRY_DSN=https://<key>@o<org_id>.ingest.sentry.io/<project_id>
SENTRY_ENVIRONMENT=production
```

Set `SENTRY_ENVIRONMENT` to `staging` on non-production instances.

When `SENTRY_DSN` is empty (default), Sentry is completely disabled. All SDK
calls (`set_tag`, `capture_exception`, `add_breadcrumb`) become no-ops, so
there is zero overhead in development or tests.

### 3. Set up alerts

In Sentry, go to **Alerts > Create Alert Rule**:

- Type: **Issue Alert**
- Conditions: "A new issue is created"
- Action: notify by email (or Discord webhook)
- Optionally filter by tag `race_id` to only alert on race-related errors

## How It Works

### HTTP endpoints

The `sentry-sdk[fastapi]` integration auto-captures unhandled exceptions in
REST endpoints. Every race endpoint (`/api/races/{race_id}/...`) is tagged with
`race_id` via a FastAPI dependency, so errors are filterable by race.

### WebSocket connections

The Sentry SDK does not auto-instrument WebSocket connections. Instead, the
base handler classes add context manually:

| Class                | Tags set                                  |
| -------------------- | ----------------------------------------- |
| `BaseHandler`        | `entity_id`, `handler` (class name)       |
| `BaseModHandler`     | `connection_type: "mod"`                  |
| `RaceModHandler`     | `participant_id`, `user` (via `set_user`) |
| `TrainingModHandler` | `user` (via `set_user`)                   |

The `race_id` tag is set at the WebSocket endpoint level in `main.py` before
the handler runs.

### Breadcrumbs

WebSocket message handlers can be decorated with `@sentry_breadcrumb` to
generate a breadcrumb on each received message. This gives a timeline of events
leading up to an error.

Currently decorated (opt-in):

- `_handle_event_flag` (zone transitions)
- `_handle_zone_query` (loading screen position queries)

Not decorated (too frequent):

- `_handle_status_update` (IGT/death count, fires every second)

To add breadcrumbs to a new handler, decorate it:

```python
from speedfog_racing.websocket.handler import sentry_breadcrumb

@sentry_breadcrumb
async def _handle_my_message(self, msg: dict[str, Any]) -> None:
    ...
```

## Searching in Sentry

Find all errors for a specific race:

```
race_id:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Find errors for a specific participant:

```
participant_id:xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx
```

Find all WebSocket errors:

```
handler:RaceModHandler
```

## Configuration Reference

| Environment variable | Default      | Description                               |
| -------------------- | ------------ | ----------------------------------------- |
| `SENTRY_DSN`         | _(empty)_    | Sentry DSN. Empty = disabled.             |
| `SENTRY_ENVIRONMENT` | `production` | Environment tag (`production`, `staging`) |

## Performance Monitoring

Performance monitoring (tracing) is currently disabled (`traces_sample_rate=0`).
To enable it, set a sample rate in `main.py`:

```python
sentry_sdk.init(
    ...
    traces_sample_rate=0.1,  # sample 10% of requests
)
```

This adds overhead and consumes Sentry quota. Only enable if you need latency
data.
