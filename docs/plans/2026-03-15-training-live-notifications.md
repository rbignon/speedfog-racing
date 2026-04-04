# Training Live Notifications Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Send a Discord notification when a player starts a solo training session while live on Twitch.

**Architecture:** Add `send_training_live_notification()` to `discord.py` with in-memory cooldown. Call it fire-and-forget from `training_mod.py` after successful auth. The function checks cooldown, queries Twitch Helix API directly via `twitch_live_service.check_live_status()`, then POSTs to a separate Discord webhook.

**Tech Stack:** Python, FastAPI, httpx, asyncio

**Spec:** `docs/specs/2026-03-15-training-live-notifications.md`

---

## File Map

- **Modify:** `server/speedfog_racing/config.py` — add `discord_training_webhook_url` setting
- **Modify:** `server/speedfog_racing/discord.py` — add `_send_training_webhook()`, cooldown logic, `send_training_live_notification()`
- **Modify:** `server/speedfog_racing/websocket/training_mod.py` — fire-and-forget call after auth
- **Create:** `server/tests/test_training_live_notification.py` — unit tests

---

### Task 1: Add config setting

**Files:**

- Modify: `server/speedfog_racing/config.py:33`

- [ ] **Step 1: Add `discord_training_webhook_url` to Settings**

In `server/speedfog_racing/config.py`, add after line 33 (`discord_webhook_url`):

```python
discord_training_webhook_url: str | None = None
```

- [ ] **Step 2: Commit**

```bash
git add server/speedfog_racing/config.py
git commit -m "config: add discord_training_webhook_url setting"
```

---

### Task 2: Add `_send_training_webhook` and cooldown in `discord.py`

**Files:**

- Modify: `server/speedfog_racing/discord.py`
- Create: `server/tests/test_training_live_notification.py`

- [ ] **Step 1: Write failing tests for cooldown and webhook logic**

Create `server/tests/test_training_live_notification.py`:

```python
"""Tests for training live Discord notifications."""

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from speedfog_racing.discord import (
    TRAINING_NOTIF_COOLDOWN_SECONDS,
    _training_notif_cooldowns,
    send_training_live_notification,
)


@pytest.fixture(autouse=True)
def clear_cooldowns():
    """Reset cooldown dict between tests."""
    _training_notif_cooldowns.clear()
    yield
    _training_notif_cooldowns.clear()


def _make_user(user_id: int = 1, username: str = "testplayer", avatar_url: str | None = "https://example.com/avatar.png") -> MagicMock:
    user = MagicMock()
    user.id = user_id
    user.twitch_username = username
    user.twitch_display_name = username.capitalize()
    user.twitch_avatar_url = avatar_url
    return user


@pytest.mark.asyncio
async def test_noop_when_no_training_webhook():
    """Should return immediately when training webhook URL is not configured."""
    user = _make_user()
    with patch("speedfog_racing.discord.settings") as mock_settings:
        mock_settings.discord_training_webhook_url = None
        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )
    # No exception, no HTTP call


@pytest.mark.asyncio
async def test_noop_when_user_not_live():
    """Should not send webhook when user is not live on Twitch."""
    user = _make_user()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook") as mock_send,
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_live.check_live_status = AsyncMock(return_value=set())

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_sends_notification_when_live():
    """Should send webhook when user is live on Twitch."""
    user = _make_user()
    mock_send = AsyncMock()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook", mock_send),
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_settings.base_url = "https://speedfog.racing"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        mock_send.assert_called_once()
        embed = mock_send.call_args[0][0]
        assert "testplayer" in embed["title"].lower() or "Testplayer" in embed["title"]
        assert embed["color"] == 0x3B82F6
        assert "session-123" in embed["url"]


@pytest.mark.asyncio
async def test_cooldown_blocks_duplicate():
    """Should not send when cooldown is active for user."""
    user = _make_user()
    _training_notif_cooldowns[user.id] = time.monotonic()

    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook") as mock_send,
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        mock_send.assert_not_called()


@pytest.mark.asyncio
async def test_cooldown_allows_after_expiry():
    """Should send when cooldown has expired."""
    user = _make_user()
    _training_notif_cooldowns[user.id] = time.monotonic() - TRAINING_NOTIF_COOLDOWN_SECONDS - 1

    mock_send = AsyncMock()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook", mock_send),
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_settings.base_url = "https://speedfog.racing"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        mock_send.assert_called_once()


@pytest.mark.asyncio
async def test_embed_contains_pool_and_links():
    """Should include pool name, stream URL, and spectator URL in embed."""
    user = _make_user()
    mock_send = AsyncMock()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook", mock_send),
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_settings.base_url = "https://speedfog.racing"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-456",
            user=user,
            pool_name="training_standard",
        )

        embed = mock_send.call_args[0][0]
        fields = {f["name"]: f["value"] for f in embed["fields"]}
        assert "Standard" in fields["Pool"]
        assert "twitch.tv/testplayer" in fields["Stream"]
        assert "session-456" in embed["url"]


@pytest.mark.asyncio
async def test_embed_has_avatar_thumbnail():
    """Should include avatar as thumbnail when available."""
    user = _make_user(avatar_url="https://example.com/avatar.png")
    mock_send = AsyncMock()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook", mock_send),
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_settings.base_url = "https://speedfog.racing"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        embed = mock_send.call_args[0][0]
        assert embed["thumbnail"]["url"] == "https://example.com/avatar.png"


@pytest.mark.asyncio
async def test_no_thumbnail_without_avatar():
    """Should omit thumbnail when user has no avatar."""
    user = _make_user(avatar_url=None)
    mock_send = AsyncMock()
    with (
        patch("speedfog_racing.discord.settings") as mock_settings,
        patch("speedfog_racing.discord.twitch_live_service") as mock_live,
        patch("speedfog_racing.discord._send_training_webhook", mock_send),
    ):
        mock_settings.discord_training_webhook_url = "https://discord.com/api/webhooks/training"
        mock_settings.base_url = "https://speedfog.racing"
        mock_live.check_live_status = AsyncMock(return_value={"testplayer"})

        await send_training_live_notification(
            session_id="session-123",
            user=user,
            pool_name="training_standard",
        )

        embed = mock_send.call_args[0][0]
        assert "thumbnail" not in embed
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd server && uv run pytest tests/test_training_live_notification.py -v
```

Expected: ImportError — `send_training_live_notification`, `_training_notif_cooldowns`, `TRAINING_NOTIF_COOLDOWN_SECONDS` do not exist yet.

- [ ] **Step 3: Implement `_send_training_webhook`, cooldown, and `send_training_live_notification`**

In `server/speedfog_racing/discord.py`, add the following imports at the top (after the existing imports):

```python
import time

from speedfog_racing.services.twitch_live import twitch_live_service
```

And in the `TYPE_CHECKING` block, add:

```python
from speedfog_racing.models import User
```

Then add at the end of the file, after `fire_race_finished_notifications`:

```python
# ---------------------------------------------------------------------------
# Training live notifications
# ---------------------------------------------------------------------------

TRAINING_NOTIF_COOLDOWN_SECONDS = 1800  # 30 minutes

# {user_id: monotonic timestamp of last notification}
_training_notif_cooldowns: dict[int, float] = {}


async def _send_training_webhook(embed: dict[str, object]) -> None:
    """Send an embed to the training Discord webhook. No-op if not configured."""
    webhook_url = settings.discord_training_webhook_url
    if not webhook_url:
        return

    payload: dict[str, object] = {"embeds": [embed]}
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.post(webhook_url, json=payload)
            if response.status_code == 429:
                retry_after = response.headers.get("Retry-After", "unknown")
                logger.warning(
                    "Discord training webhook rate limited, retry after %s seconds",
                    retry_after,
                )
            elif response.status_code >= 400:
                logger.warning("Discord training webhook failed with status %d", response.status_code)
    except Exception as e:
        logger.warning("Discord training webhook error: %s", e)


def _check_training_cooldown(user_id: int) -> bool:
    """Check if a training notification can be sent for this user.

    Returns True if allowed (no active cooldown). Prunes expired entries.
    """
    now = time.monotonic()
    # Prune expired entries
    expired = [uid for uid, ts in _training_notif_cooldowns.items() if now - ts >= TRAINING_NOTIF_COOLDOWN_SECONDS]
    for uid in expired:
        del _training_notif_cooldowns[uid]

    last = _training_notif_cooldowns.get(user_id)
    if last is not None and now - last < TRAINING_NOTIF_COOLDOWN_SECONDS:
        logger.debug("Training notification cooldown active for user %d", user_id)
        return False
    return True


async def send_training_live_notification(
    *,
    session_id: str,
    user: User,
    pool_name: str,
) -> None:
    """Send Discord notification for a live training session.

    Checks webhook config, cooldown, and Twitch live status before sending.
    Designed to be called via fire-and-forget asyncio.create_task().
    """
    if not settings.discord_training_webhook_url:
        return

    if not _check_training_cooldown(user.id):
        return

    # Direct Twitch API check (not from polling cache which only covers races)
    live_usernames = await twitch_live_service.check_live_status([user.twitch_username])
    if user.twitch_username.lower() not in live_usernames:
        return

    display_name = user.twitch_display_name or user.twitch_username
    display_pool = format_pool_display_name(pool_name)
    stream_url = f"https://twitch.tv/{user.twitch_username}"
    base_url = settings.base_url.rstrip("/")

    embed: dict[str, object] = {
        "title": f"🎮 {display_name} started a solo SpeedFog run!",
        "url": f"{base_url}/training/{session_id}",
        "color": 0x3B82F6,  # blue (training/solo)
        "fields": [
            {"name": "Pool", "value": display_pool, "inline": True},
            {"name": "Stream", "value": f"[twitch.tv/{user.twitch_username}]({stream_url})", "inline": True},
        ],
    }
    if user.twitch_avatar_url:
        embed["thumbnail"] = {"url": user.twitch_avatar_url}

    await _send_training_webhook(embed)

    # Record cooldown on success
    _training_notif_cooldowns[user.id] = time.monotonic()
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd server && uv run pytest tests/test_training_live_notification.py -v
```

Expected: all tests PASS.

- [ ] **Step 5: Run full test suite to check for regressions**

```bash
cd server && uv run pytest -x -q
```

Expected: no failures.

- [ ] **Step 6: Run linters**

```bash
cd server && uv run ruff check speedfog_racing/discord.py && uv run ruff format speedfog_racing/discord.py && uv run mypy speedfog_racing/discord.py
```

- [ ] **Step 7: Commit**

```bash
git add server/speedfog_racing/discord.py server/tests/test_training_live_notification.py
git commit -m "feat: add training live notification with cooldown to discord.py"
```

---

### Task 3: Wire up fire-and-forget call in training_mod.py

**Files:**

- Modify: `server/speedfog_racing/websocket/training_mod.py:123-148`

- [ ] **Step 1: Add the fire-and-forget call after auth_ok**

In `server/speedfog_racing/websocket/training_mod.py`, add this import at the top (with the other imports):

```python
from speedfog_racing.discord import send_training_live_notification
```

Then, after line 148 (`await _broadcast_participant_update(session, spectator_only=True)`), add:

```python
        # Fire-and-forget: notify Discord if player is live on Twitch
        notif_task = asyncio.create_task(
            send_training_live_notification(
                session_id=str(session.id),
                user=session.user,
                pool_name=session.seed.pool_name if session.seed else "training_standard",
            )
        )
        notif_task.add_done_callback(lambda t: t.exception() if not t.cancelled() else None)
```

Note: `session.user` and `session.seed` are available here because they were eagerly loaded via `_load_options()` (line 50-54) and `expire_on_commit=False` keeps them accessible after the DB session closes.

- [ ] **Step 2: Run existing training tests to check no regression**

```bash
cd server && uv run pytest tests/test_training.py -v -x
```

Expected: all pass.

- [ ] **Step 3: Run linters**

```bash
cd server && uv run ruff check speedfog_racing/websocket/training_mod.py && uv run mypy speedfog_racing/websocket/training_mod.py
```

- [ ] **Step 4: Commit**

```bash
git add server/speedfog_racing/websocket/training_mod.py
git commit -m "feat: fire training live notification on mod auth"
```

---

### Task 4: Final verification

- [ ] **Step 1: Run full test suite**

```bash
cd server && uv run pytest -x -q
```

- [ ] **Step 2: Run all linters**

```bash
cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy speedfog_racing/
```

- [ ] **Step 3: Verify config documentation**

Check that `DISCORD_TRAINING_WEBHOOK_URL` is documented if there's an `.env.example` or deployment docs that list env vars.

```bash
grep -r "DISCORD_WEBHOOK_URL" deploy/ docs/ server/.env* 2>/dev/null || true
```

If there's an `.env.example` or deployment README listing Discord vars, add `DISCORD_TRAINING_WEBHOOK_URL` next to `DISCORD_WEBHOOK_URL`.
