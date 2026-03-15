# Training Live Notifications

Discord notifications when a player starts a training session while live on Twitch.

## Trigger

When the mod authenticates on the training WebSocket (`/ws/training/{session_id}/mod`), after sending `auth_ok`:

1. Fire-and-forget a background task that:
   a. Checks the per-user cooldown (30 min default) — bail early if throttled
   b. Calls the Twitch Helix API directly to check if the player is live
   c. If live, sends the Discord webhook notification

The Twitch live check is done inside the background task (not via `TwitchLiveService`) because the polling service only tracks users in active races, not training sessions. A direct API call is more reliable and adds no latency to the auth flow since it runs in the background.

## Configuration

New environment variable:

- `DISCORD_TRAINING_WEBHOOK_URL` — separate webhook URL for training notifications. If absent, no training notifications are sent.

Add to `config.py` as an optional field (`str | None = None`).

## Discord Embed

- **Color**: blue (`0x3B82F6`, matching the training/solo color in `discord.py`)
- **Title**: `{twitch_username} is training on SpeedFog!`
- **Fields**: Pool name
- **Links**: Twitch stream URL + spectator page URL (`{BASE_URL}/training/{session_id}`)
- **Thumbnail**: player's Twitch avatar (if available from `User.twitch_avatar_url`)

## Cooldown

- In-memory dict in `discord.py`: `_training_notif_cooldowns: dict[int, float]` mapping `user_id` to last notification timestamp
- Default cooldown: 30 minutes (module-level constant `TRAINING_NOTIF_COOLDOWN_SECONDS = 1800`)
- Passive cleanup: prune expired entries during each check to keep the dict bounded
- Consistent with existing in-memory patterns (`TwitchLiveService._live_usernames`, `ConnectionManager`)

## Implementation

### New function in `discord.py`

```python
async def send_training_live_notification(
    session_id: str,
    user: User,
    pool_name: str,
) -> None:
```

1. Check `DISCORD_TRAINING_WEBHOOK_URL` is configured, else return
2. Check cooldown for `user.id`, else return (prune expired entries, log at DEBUG)
3. Call `twitch_live_service.check_live_status([user.twitch_username])` — this is an instance method on the module-level singleton from `services/twitch_live.py`. It makes a direct Helix API call and returns a `set[str]` of live usernames (stateless, no side effects on the singleton's cache).
4. If username not in returned set, return
5. Build embed with stream URL as `https://twitch.tv/{user.twitch_username}`
6. POST to webhook
7. Update cooldown timestamp on success

Assumes Twitch credentials (`TWITCH_CLIENT_ID`, `TWITCH_CLIENT_SECRET`) are configured — any deployed instance with Discord webhooks will have these. Errors are caught by the `add_done_callback` on the task.

### Call site in `training_mod.py`

After successful auth (`auth_ok` sent), in the existing auth success block:

```python
from speedfog_racing.discord import send_training_live_notification

task = asyncio.create_task(
    send_training_live_notification(
        session_id=str(session.id),
        user=user,
        pool_name=session.seed.pool_name,
    )
)
task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
```

Fire-and-forget with `add_done_callback` for exception logging, same pattern as race notifications in `api/races.py`.

## Scope

No changes to:

- **Frontend** — no UI additions
- **Mod** — no protocol changes
- **Database** — no model changes
- **Training WebSocket protocol** — no new messages
- **TwitchLiveService** — polling scope unchanged

## Testing

- Unit test for cooldown logic (throttled vs. allowed)
- Unit test for webhook URL absent (no-op)
- Integration test: mock Twitch API response as live, verify webhook POST is made after mod auth

## Notification policy

- Automatic for all live players (no opt-in/opt-out)
- Being live on Twitch is implicit consent to visibility
- Only on mod auth (session start), not on finish/abandon
- Cooldown prevents spam when players chain sessions
