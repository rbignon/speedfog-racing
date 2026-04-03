# Persistent Chat with Dual Channels - Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the in-memory single-channel race chat with two persistent, DB-backed channels (Participants + Public) with server-side visibility filtering and automatic cleanup.

**Architecture:** New `ChatMessage` DB model stores messages per channel. WebSocket spectator handler validates channel access and persists on receive. `SpectatorConnection` extended with role/participant metadata for server-side broadcast filtering. Frontend `ChatSidebar` gains tab UI with per-channel unread tracking.

**Tech Stack:** Python/FastAPI, SQLAlchemy async, Alembic, SvelteKit 5 (runes), WebSocket

**Spec:** `docs/plans/2026-04-03-persistent-chat-channels.md`

---

## File Structure

**New files:**

- `server/speedfog_racing/services/chat_cleanup.py` - Background cleanup task
- `server/alembic/versions/*_add_chat_message_table.py` - Migration (auto-generated)
- `server/tests/test_chat_persistence.py` - Chat persistence + access control tests
- `server/tests/test_chat_cleanup.py` - Cleanup task tests

**Modified files:**

- `server/speedfog_racing/models.py` - ChatChannel enum, ChatMessage model, Race.finished_at
- `server/speedfog_racing/websocket/schemas.py` - SendChatMessage, ChatBroadcastMessage, ChatHistoryMessage
- `server/speedfog_racing/websocket/manager.py` - SpectatorConnection metadata, channel broadcast methods
- `server/speedfog_racing/websocket/spectator.py` - Channel validation, persistence, history delivery
- `server/speedfog_racing/websocket/mod.py` - PUBLIC history on participant finish, is_playing update on race_start
- `server/speedfog_racing/services/race_lifecycle.py` - Set Race.finished_at
- `server/speedfog_racing/api/races.py` - Set Race.finished_at on manual finish
- `server/speedfog_racing/main.py` - Register chat cleanup background task
- `server/tests/test_chat_websocket.py` - Update existing schema tests
- `web/src/lib/websocket.ts` - Channel field, ChatHistoryMessage type
- `web/src/lib/stores/race.svelte.ts` - Dual message arrays, chat_history handler
- `web/src/lib/components/ChatSidebar.svelte` - Tab UI, unread badges, grayed state
- `web/src/lib/components/ChatPanel.svelte` - Minor: empty-state text per channel
- `web/src/routes/race/[id]/+page.svelte` - Channel context, tab visibility, send with channel

---

### Task 1: Data Model (ChatChannel, ChatMessage, Race.finished_at)

**Files:**

- Modify: `server/speedfog_racing/models.py`
- Create: `server/alembic/versions/*_add_chat_message_table.py`
- Test: `server/tests/test_chat_persistence.py`

- [ ] **Step 1: Add ChatChannel enum and ChatMessage model**

In `server/speedfog_racing/models.py`, add after the existing enums (after line 68):

```python
class ChatChannel(str, enum.Enum):
    """Chat channel types."""

    PARTICIPANTS = "participants"
    PUBLIC = "public"
```

Add the ChatMessage model after the PlayerTraitScores class (after line 313):

```python
class ChatMessage(Base):
    """A persisted chat message in a race channel."""

    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_race_channel_created", "race_id", "channel", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    race_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("races.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[ChatChannel] = mapped_column(Enum(ChatChannel), nullable=False)
    user_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False
    )
    message: Mapped[str] = mapped_column(String(500), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now()
    )

    race: Mapped["Race"] = relationship()
    user: Mapped["User"] = relationship()
```

- [ ] **Step 2: Add finished_at to Race model**

In `server/speedfog_racing/models.py`, add after `discord_event_id` (line 157) in the Race class:

```python
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
```

- [ ] **Step 3: Generate alembic migration**

Run:

```bash
cd server && uv run alembic revision --autogenerate -m "add chat_message table and race finished_at"
```

Review the generated migration to verify it creates the `chat_messages` table with the composite index and adds `finished_at` to `races`.

- [ ] **Step 4: Run migration and verify**

Run:

```bash
cd server && uv run alembic upgrade head
```

- [ ] **Step 5: Write model test**

Create `server/tests/test_chat_persistence.py`:

```python
"""Tests for chat message persistence."""

import pytest
from pydantic import ValidationError

from speedfog_racing.models import ChatChannel


@pytest.mark.asyncio
async def test_chat_channel_enum():
    """ChatChannel enum has expected values."""
    assert ChatChannel.PARTICIPANTS == "participants"
    assert ChatChannel.PUBLIC == "public"
    assert len(ChatChannel) == 2
```

- [ ] **Step 6: Run test to verify it passes**

Run: `cd server && uv run pytest tests/test_chat_persistence.py -v`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add server/speedfog_racing/models.py server/alembic/versions/ server/tests/test_chat_persistence.py
git commit -m "feat: add ChatMessage model, ChatChannel enum, and Race.finished_at"
```

---

### Task 2: WebSocket Schemas

**Files:**

- Modify: `server/speedfog_racing/websocket/schemas.py`
- Modify: `server/tests/test_chat_websocket.py`

- [ ] **Step 1: Update SendChatMessage with channel field**

In `server/speedfog_racing/websocket/schemas.py`, update `SendChatMessage` (lines 220-225):

```python
class SendChatMessage(BaseModel):
    """Chat message from authenticated spectator/caster."""

    type: Literal["chat"] = "chat"
    channel: str = Field(pattern=r"^(participants|public)$")
    message: str = Field(max_length=500)
```

- [ ] **Step 2: Update ChatBroadcastMessage with channel field**

In `server/speedfog_racing/websocket/schemas.py`, update `ChatBroadcastMessage` (lines 230-241):

```python
class ChatBroadcastMessage(BaseModel):
    """Chat message broadcast to room."""

    type: Literal["chat_message"] = "chat_message"
    channel: str  # "participants" | "public"
    username: str
    display_name: str | None
    avatar_url: str | None
    role: str  # "organizer" | "admin" | "caster" | "participant"
    dominant_trait: str | None  # e.g. "rusher", "explorer", null
    message: str
    timestamp: str  # ISO format from server
```

- [ ] **Step 3: Add ChatHistoryMessage schema**

In `server/speedfog_racing/websocket/schemas.py`, add after `ChatBroadcastMessage`:

```python
class ChatHistoryMessage(BaseModel):
    """Chat history sent on connection for a specific channel."""

    type: Literal["chat_history"] = "chat_history"
    channel: str  # "participants" | "public"
    messages: list[ChatBroadcastMessage]
```

- [ ] **Step 4: Update existing schema tests**

In `server/tests/test_chat_websocket.py`, update tests:

```python
"""Tests for chat WebSocket messages."""

import pytest


@pytest.mark.asyncio
async def test_chat_message_schema():
    """ChatBroadcastMessage serializes correctly with channel."""
    from speedfog_racing.websocket.schemas import ChatBroadcastMessage

    msg = ChatBroadcastMessage(
        channel="participants",
        username="testuser",
        display_name="TestUser",
        avatar_url=None,
        role="participant",
        dominant_trait="rusher",
        message="Hello race!",
        timestamp="2026-03-23T12:00:00+00:00",
    )
    data = msg.model_dump()
    assert data["type"] == "chat_message"
    assert data["channel"] == "participants"
    assert data["username"] == "testuser"
    assert data["message"] == "Hello race!"
    assert data["role"] == "participant"
    assert data["dominant_trait"] == "rusher"


@pytest.mark.asyncio
async def test_send_chat_message_schema():
    """SendChatMessage validates correctly with channel."""
    from speedfog_racing.websocket.schemas import SendChatMessage

    msg = SendChatMessage(channel="public", message="Hello!")
    assert msg.type == "chat"
    assert msg.channel == "public"
    assert msg.message == "Hello!"


@pytest.mark.asyncio
async def test_send_chat_message_max_length():
    """SendChatMessage rejects messages over 500 chars."""
    from pydantic import ValidationError

    from speedfog_racing.websocket.schemas import SendChatMessage

    with pytest.raises(ValidationError):
        SendChatMessage(channel="public", message="x" * 501)


@pytest.mark.asyncio
async def test_send_chat_message_invalid_channel():
    """SendChatMessage rejects invalid channel names."""
    from pydantic import ValidationError

    from speedfog_racing.websocket.schemas import SendChatMessage

    with pytest.raises(ValidationError):
        SendChatMessage(channel="spoiler", message="Hello!")


@pytest.mark.asyncio
async def test_chat_history_message_schema():
    """ChatHistoryMessage serializes correctly."""
    from speedfog_racing.websocket.schemas import ChatBroadcastMessage, ChatHistoryMessage

    history = ChatHistoryMessage(
        channel="participants",
        messages=[
            ChatBroadcastMessage(
                channel="participants",
                username="user1",
                display_name="User 1",
                avatar_url=None,
                role="participant",
                dominant_trait=None,
                message="Ready!",
                timestamp="2026-04-03T12:00:00+00:00",
            )
        ],
    )
    data = history.model_dump()
    assert data["type"] == "chat_history"
    assert data["channel"] == "participants"
    assert len(data["messages"]) == 1
    assert data["messages"][0]["username"] == "user1"
```

- [ ] **Step 5: Run tests**

Run: `cd server && uv run pytest tests/test_chat_websocket.py -v`
Expected: all 5 tests PASS

- [ ] **Step 6: Commit**

```bash
git add server/speedfog_racing/websocket/schemas.py server/tests/test_chat_websocket.py
git commit -m "feat: add channel field to chat schemas, add ChatHistoryMessage"
```

---

### Task 3: SpectatorConnection Metadata + Channel Broadcast Methods

**Files:**

- Modify: `server/speedfog_racing/websocket/manager.py`

- [ ] **Step 1: Extend SpectatorConnection**

In `server/speedfog_racing/websocket/manager.py`, update the `SpectatorConnection` dataclass (lines 38-44):

```python
@dataclass
class SpectatorConnection:
    """A connected spectator client."""

    websocket: WebSocket
    user_id: uuid.UUID | None = None
    locale: str = "en"
    role: str | None = None  # "organizer" | "admin" | "caster" | "participant"
    participant_id: uuid.UUID | None = None
    is_playing: bool = False  # True if participant currently in PLAYING status during RUNNING
```

- [ ] **Step 2: Add channel-filtered broadcast methods to RaceRoom**

In `server/speedfog_racing/websocket/manager.py`, add to the `RaceRoom` class after `broadcast_to_all` (after line 112):

```python
    async def broadcast_chat_participants(self, message: str) -> None:
        """Broadcast to spectator connections with a race role (participant/organizer/caster/admin)."""
        snapshot = [c for c in self.spectators if c.role is not None]
        if not snapshot:
            return
        failed: list[SpectatorConnection] = []
        async def _send(conn: SpectatorConnection) -> None:
            try:
                await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
            except Exception:
                failed.append(conn)
        await asyncio.gather(*(_send(c) for c in snapshot))
        for conn in failed:
            try:
                self.spectators.remove(conn)
            except ValueError:
                pass

    async def broadcast_chat_public(self, message: str) -> None:
        """Broadcast to authenticated spectators, excluding playing participants."""
        snapshot = [c for c in self.spectators if c.user_id is not None and not c.is_playing]
        if not snapshot:
            return
        failed: list[SpectatorConnection] = []
        async def _send(conn: SpectatorConnection) -> None:
            try:
                await asyncio.wait_for(conn.websocket.send_text(message), timeout=SEND_TIMEOUT)
            except Exception:
                failed.append(conn)
        await asyncio.gather(*(_send(c) for c in snapshot))
        for conn in failed:
            try:
                self.spectators.remove(conn)
            except ValueError:
                pass
```

- [ ] **Step 3: Add helper to find spectator connection by user_id**

In `server/speedfog_racing/websocket/manager.py`, add to the `RaceRoom` class:

```python
    def get_spectator_by_user_id(self, user_id: uuid.UUID) -> SpectatorConnection | None:
        """Find a spectator connection by user ID."""
        for conn in self.spectators:
            if conn.user_id == user_id:
                return conn
        return None
```

- [ ] **Step 4: Commit**

```bash
git add server/speedfog_racing/websocket/manager.py
git commit -m "feat: extend SpectatorConnection with role/participant metadata, add channel broadcast methods"
```

---

### Task 4: Chat Persistence + Channel Access Control (Server)

**Files:**

- Modify: `server/speedfog_racing/websocket/spectator.py`
- Modify: `server/tests/test_chat_persistence.py`

- [ ] **Step 1: Update spectator handler to set connection metadata**

In `server/speedfog_racing/websocket/spectator.py`, after role determination (line 124), store role and participant info on the connection:

```python
                if role is not None and user_obj is not None:
                    conn.role = role

                    # Track participant info for broadcast filtering
                    if role == "participant":
                        participant = next(
                            (p for p in race.participants if p.user_id == user_id), None
                        )
                        if participant:
                            conn.participant_id = participant.id
                            conn.is_playing = (
                                race.status == RaceStatus.RUNNING
                                and participant.status == ParticipantStatus.PLAYING
                            )
```

Also update the `chat_info` dict to allow logged-in spectators (no race role) to write in PUBLIC. Change the `chat_info` setup: all authenticated users get chat_info, but with `role=None` for pure spectators. The existing `chat_info is None` check must be replaced with channel-specific access checks.

Replace the chat_info block (lines 126-137) with:

```python
                if user_obj is not None:
                    if role is not None:
                        conn.role = role

                        if role == "participant":
                            participant = next(
                                (p for p in race.participants if p.user_id == user_id), None
                            )
                            if participant:
                                conn.participant_id = participant.id
                                conn.is_playing = (
                                    race.status == RaceStatus.RUNNING
                                    and participant.status == ParticipantStatus.PLAYING
                                )

                    # Load dominant_trait from PlayerTraitScores
                    trait_scores = await db.get(PlayerTraitScores, user_id)
                    dominant_trait = trait_scores.dominant_trait if trait_scores else None

                    chat_info = {
                        "username": user_obj.twitch_username,
                        "display_name": user_obj.twitch_display_name,
                        "avatar_url": user_obj.twitch_avatar_url,
                        "role": role or "spectator",
                        "dominant_trait": dominant_trait,
                    }
```

- [ ] **Step 2: Update chat message handling with channel validation and persistence**

Replace the chat handling block in the message loop (lines 167-189) with:

```python
                if msg_type == "chat":
                    if chat_info is None:
                        continue  # Not authenticated

                    try:
                        chat_msg = SendChatMessage.model_validate(msg)
                    except Exception:
                        continue

                    # Validate channel access
                    channel = chat_msg.channel
                    if channel == "participants" and conn.role is None:
                        continue  # Spectators cannot write to participants channel
                    if channel == "public" and conn.is_playing:
                        continue  # Playing participants cannot write to public

                    room = manager.get_room(race_id)
                    if room is None:
                        continue

                    broadcast = ChatBroadcastMessage(
                        channel=channel,
                        username=chat_info["username"],
                        display_name=chat_info["display_name"],
                        avatar_url=chat_info["avatar_url"],
                        role=chat_info["role"],
                        dominant_trait=chat_info["dominant_trait"],
                        message=chat_msg.message,
                        timestamp=datetime.now(UTC).isoformat(),
                    )

                    # Persist to DB
                    async with session_maker() as db:
                        db_msg = ChatMessageModel(
                            race_id=race_id,
                            channel=ChatChannel(channel),
                            user_id=conn.user_id,
                            message=chat_msg.message,
                        )
                        db.add(db_msg)
                        await db.commit()

                    # Broadcast to appropriate connections
                    msg_json = broadcast.model_dump_json()
                    if channel == "participants":
                        await room.broadcast_chat_participants(msg_json)
                    else:
                        await room.broadcast_chat_public(msg_json)
```

Add the necessary imports at the top of `spectator.py`:

```python
from speedfog_racing.models import ChatChannel, ChatMessage as ChatMessageModel, ParticipantStatus, RaceStatus
```

(Alias `ChatMessage` to `ChatMessageModel` to avoid conflict with the WS schema `ChatBroadcastMessage`.)

- [ ] **Step 3: Write access control tests**

Add to `server/tests/test_chat_persistence.py`:

```python
@pytest.mark.asyncio
async def test_send_chat_message_channel_validation():
    """SendChatMessage validates channel field."""
    from speedfog_racing.websocket.schemas import SendChatMessage

    # Valid channels
    msg = SendChatMessage(channel="participants", message="test")
    assert msg.channel == "participants"

    msg = SendChatMessage(channel="public", message="test")
    assert msg.channel == "public"

    # Invalid channel
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        SendChatMessage(channel="invalid", message="test")
```

- [ ] **Step 4: Run tests**

Run: `cd server && uv run pytest tests/test_chat_persistence.py tests/test_chat_websocket.py -v`
Expected: all tests PASS

- [ ] **Step 5: Run linters**

Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`
Fix any issues.

- [ ] **Step 6: Commit**

```bash
git add server/speedfog_racing/websocket/spectator.py server/tests/test_chat_persistence.py
git commit -m "feat: add channel access control and DB persistence for chat messages"
```

---

### Task 5: Chat History on Connect

**Files:**

- Modify: `server/speedfog_racing/websocket/spectator.py`

- [ ] **Step 1: Add helper function to load and send chat history**

In `server/speedfog_racing/websocket/spectator.py`, add a helper function before `handle_spectator_websocket`:

```python
async def _send_chat_history(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    race_id: uuid.UUID,
    channel: ChatChannel,
) -> None:
    """Load chat history from DB and send to client."""
    async with session_maker() as db:
        result = await db.execute(
            select(ChatMessageModel, User)
            .join(User, ChatMessageModel.user_id == User.id)
            .where(
                ChatMessageModel.race_id == race_id,
                ChatMessageModel.channel == channel,
            )
            .order_by(ChatMessageModel.created_at.asc())
        )
        rows = result.all()

    messages = []
    for chat_msg, user in rows:
        # Resolve role and trait at load time (not stored in message)
        # For history, we use the role stored in the original broadcast
        # but we skip full resolution here for simplicity; the DB message
        # does not store role/trait, so we load them fresh.
        trait_scores_result = None
        async with session_maker() as db:
            trait_scores = await db.get(PlayerTraitScores, chat_msg.user_id)
            dominant_trait = trait_scores.dominant_trait if trait_scores else None

        messages.append(
            ChatBroadcastMessage(
                channel=channel.value,
                username=user.twitch_username,
                display_name=user.twitch_display_name,
                avatar_url=user.twitch_avatar_url,
                role="participant",  # Will be resolved properly in step 2
                dominant_trait=dominant_trait,
                message=chat_msg.message,
                timestamp=chat_msg.created_at.isoformat(),
            )
        )

    history = ChatHistoryMessage(
        channel=channel.value,
        messages=messages,
    )
    await websocket.send_text(history.model_dump_json())
```

- [ ] **Step 2: Improve history helper with proper role resolution**

The role resolution needs race context. Refactor the helper to batch-load roles:

```python
async def _send_chat_history(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    race_id: uuid.UUID,
    race: Race,
    channel: ChatChannel,
) -> None:
    """Load chat history from DB and send to client."""
    async with session_maker() as db:
        result = await db.execute(
            select(ChatMessageModel, User)
            .join(User, ChatMessageModel.user_id == User.id)
            .where(
                ChatMessageModel.race_id == race_id,
                ChatMessageModel.channel == channel,
            )
            .order_by(ChatMessageModel.created_at.asc())
        )
        rows = result.all()

        if not rows:
            # Send empty history so client knows channel is loaded
            history = ChatHistoryMessage(channel=channel.value, messages=[])
            await websocket.send_text(history.model_dump_json())
            return

        # Batch-load trait scores for all unique users
        user_ids = list({chat_msg.user_id for chat_msg, _ in rows})
        trait_results = await db.execute(
            select(PlayerTraitScores).where(PlayerTraitScores.user_id.in_(user_ids))
        )
        traits_by_user = {t.user_id: t.dominant_trait for t in trait_results.scalars()}

    # Build role lookup from race relationships (already loaded)
    participant_user_ids = {p.user_id for p in race.participants}
    caster_user_ids = {c.user_id for c in race.casters}

    def _resolve_role(user: User) -> str:
        if race.organizer_id == user.id:
            return "organizer"
        if user.role == UserRole.ADMIN:
            return "admin"
        if user.id in caster_user_ids:
            return "caster"
        if user.id in participant_user_ids:
            return "participant"
        return "spectator"

    messages = []
    for chat_msg, user in rows:
        messages.append(
            ChatBroadcastMessage(
                channel=channel.value,
                username=user.twitch_username,
                display_name=user.twitch_display_name,
                avatar_url=user.twitch_avatar_url,
                role=_resolve_role(user),
                dominant_trait=traits_by_user.get(chat_msg.user_id),
                message=chat_msg.message,
                timestamp=chat_msg.created_at.isoformat(),
            )
        )

    history = ChatHistoryMessage(channel=channel.value, messages=messages)
    await websocket.send_text(history.model_dump_json())
```

Add import for `UserRole` at top of file:

```python
from speedfog_racing.models import UserRole
```

Add import for `ChatHistoryMessage`:

```python
from speedfog_racing.websocket.schemas import ChatHistoryMessage
```

- [ ] **Step 3: Send chat history after auth in handle_spectator_websocket**

After `send_race_state` (line 140) and before the session closes, send chat history based on the user's access level. Actually, since session_maker is available, do it after `connect_spectator` (line 144) and before the heartbeat loop:

```python
        # Register connection
        await manager.connect_spectator(race_id, conn)

        # Send chat history for accessible channels
        if conn.role is not None:
            # Participants, organizers, casters, admins see PARTICIPANTS channel
            await _send_chat_history(websocket, session_maker, race_id, race, ChatChannel.PARTICIPANTS)
        if conn.user_id is not None and not conn.is_playing:
            # Authenticated users who are not currently playing see PUBLIC
            await _send_chat_history(websocket, session_maker, race_id, race, ChatChannel.PUBLIC)
```

Note: `race` is a detached object here (session closed at line 141), but with `expire_on_commit=False` its attributes are still readable. The relationships (participants, casters) were eagerly loaded by `get_race_with_details`.

- [ ] **Step 4: Run linters**

Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`

- [ ] **Step 5: Commit**

```bash
git add server/speedfog_racing/websocket/spectator.py
git commit -m "feat: send chat history on WebSocket connect based on channel access"
```

---

### Task 6: Participant Finish Transition + Race Start

**Files:**

- Modify: `server/speedfog_racing/websocket/mod.py`
- Modify: `server/speedfog_racing/websocket/spectator.py`

- [ ] **Step 1: Send PUBLIC chat history when participant finishes**

In `server/speedfog_racing/websocket/mod.py`, in `handle_finished` (after line 808), after the leaderboard broadcast, add logic to unlock PUBLIC for the finishing participant's spectator connection:

```python
    # Unlock PUBLIC channel for finished participant's spectator connection
    room = manager.get_room(participant.race_id)
    if room:
        spec_conn = room.get_spectator_by_user_id(participant.user_id)
        if spec_conn and spec_conn.is_playing:
            spec_conn.is_playing = False
            # Send PUBLIC chat history catch-up
            await _send_public_chat_history(
                spec_conn.websocket, session_maker, participant.race_id, participant.race
            )
```

Add the helper import and a thin wrapper in `mod.py`:

```python
from speedfog_racing.websocket.spectator import _send_chat_history
from speedfog_racing.models import ChatChannel


async def _send_public_chat_history(
    websocket: WebSocket,
    session_maker: async_sessionmaker[AsyncSession],
    race_id: uuid.UUID,
    race: Race,
) -> None:
    """Send PUBLIC channel history to a participant who just finished."""
    try:
        await _send_chat_history(websocket, session_maker, race_id, race, ChatChannel.PUBLIC)
    except Exception:
        logger.warning("Failed to send public chat history to finished participant")
```

- [ ] **Step 2: Set is_playing on race start**

In `server/speedfog_racing/websocket/mod.py`, find `broadcast_race_start` (line 811). After this function broadcasts `race_start`, we need to set `is_playing = True` on all participant spectator connections. The race start is called from the API endpoint; let's add a function in `manager.py` and call it from where `broadcast_race_start` is invoked.

In `server/speedfog_racing/websocket/manager.py`, add a method to `RaceRoom`:

```python
    def mark_participants_playing(self) -> None:
        """Set is_playing=True on all participant spectator connections."""
        for conn in self.spectators:
            if conn.role == "participant":
                conn.is_playing = True
```

Then in the race start API handler. Find where `broadcast_race_start` is called in `server/speedfog_racing/api/races.py`:

```python
# After the race start broadcast, mark participants as playing
room = manager.get_room(race_id)
if room:
    room.mark_participants_playing()
```

Add import of `manager` from `websocket.manager` in `api/races.py` (it may already be imported).

- [ ] **Step 3: Run linters**

Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`

- [ ] **Step 4: Commit**

```bash
git add server/speedfog_racing/websocket/mod.py server/speedfog_racing/websocket/manager.py server/speedfog_racing/websocket/spectator.py server/speedfog_racing/api/races.py
git commit -m "feat: unlock PUBLIC channel on participant finish, set is_playing on race start"
```

---

### Task 7: Race.finished_at + Cleanup Background Task

**Files:**

- Modify: `server/speedfog_racing/services/race_lifecycle.py`
- Modify: `server/speedfog_racing/api/races.py`
- Create: `server/speedfog_racing/services/chat_cleanup.py`
- Modify: `server/speedfog_racing/main.py`
- Create: `server/tests/test_chat_cleanup.py`

- [ ] **Step 1: Set finished_at in auto-finish**

In `server/speedfog_racing/services/race_lifecycle.py`, update the values dict in `check_race_auto_finish` (line 40):

```python
        .values(status=RaceStatus.FINISHED, version=race.version + 1, finished_at=datetime.now(UTC))
```

Also update the in-memory object (after line 48):

```python
    race.status = RaceStatus.FINISHED
    race.version += 1
    race.finished_at = datetime.now(UTC)
```

Add the import at the top:

```python
from datetime import UTC, datetime
```

- [ ] **Step 2: Set finished_at in manual finish**

In `server/speedfog_racing/api/races.py`, in the `finish_race` endpoint (line 1391), pass `finished_at` to `_transition_status`:

```python
    await _transition_status(
        db, race, [RaceStatus.RUNNING], RaceStatus.FINISHED, finished_at=datetime.now(UTC)
    )
```

The `_transition_status` helper already accepts `**extra_fields` and passes them to `.values()`, so this works without modification.

Add `from datetime import UTC` if not already imported (check existing imports in the file).

- [ ] **Step 3: Create chat cleanup service**

Create `server/speedfog_racing/services/chat_cleanup.py`:

```python
"""Background task to clean up old chat messages."""

import asyncio
import logging

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from speedfog_racing.models import ChatMessage, Race, RaceStatus

from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

CLEANUP_INTERVAL_SECONDS = 3600  # 1 hour
RETENTION_HOURS = 24


async def cleanup_old_chat_messages(session_maker: async_sessionmaker[AsyncSession]) -> int:
    """Delete chat messages from races finished more than RETENTION_HOURS ago.

    Returns the number of deleted messages.
    """
    cutoff = datetime.now(UTC) - timedelta(hours=RETENTION_HOURS)

    async with session_maker() as db:
        # Find races finished before cutoff
        finished_race_ids = await db.execute(
            select(Race.id).where(
                Race.status == RaceStatus.FINISHED,
                Race.finished_at.is_not(None),
                Race.finished_at < cutoff,
            )
        )
        race_ids = [row[0] for row in finished_race_ids.fetchall()]

        if not race_ids:
            return 0

        result = await db.execute(
            delete(ChatMessage).where(ChatMessage.race_id.in_(race_ids))
        )
        count = result.rowcount  # type: ignore[assignment]
        await db.commit()

    return count


async def chat_cleanup_loop(session_maker: async_sessionmaker[AsyncSession]) -> None:
    """Periodically clean up old chat messages."""
    while True:
        try:
            await asyncio.sleep(CLEANUP_INTERVAL_SECONDS)
            count = await cleanup_old_chat_messages(session_maker)
            if count > 0:
                logger.info("Cleaned up %d old chat messages", count)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("Error in chat cleanup loop")
```

- [ ] **Step 4: Register cleanup task in lifespan**

In `server/speedfog_racing/main.py`, add the import:

```python
from speedfog_racing.services.chat_cleanup import chat_cleanup_loop
```

In the lifespan function, after the Twitch live polling task setup (around line 70), add:

```python
    # Start chat cleanup loop
    chat_cleanup_task = asyncio.create_task(chat_cleanup_loop(async_session_maker))
```

In the shutdown section, cancel it:

```python
    chat_cleanup_task.cancel()
    try:
        await chat_cleanup_task
    except asyncio.CancelledError:
        pass
```

- [ ] **Step 5: Write cleanup test**

Create `server/tests/test_chat_cleanup.py`:

```python
"""Tests for chat message cleanup."""

import uuid
from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock

import pytest

from speedfog_racing.models import ChatChannel, ChatMessage, Race, RaceStatus
from speedfog_racing.services.chat_cleanup import cleanup_old_chat_messages


@pytest.mark.asyncio
async def test_cleanup_deletes_old_messages(client):
    """Messages from races finished > 24h ago are deleted."""
    from speedfog_racing.database import Base
    from tests.conftest import TestingSessionLocal

    db = TestingSessionLocal()
    try:
        # Create a finished race with old finished_at
        race_id = uuid.uuid4()
        user_id = uuid.uuid4()
        from speedfog_racing.models import User, UserRole

        user = User(
            id=user_id,
            twitch_id=f"test_{uuid.uuid4().hex[:8]}",
            twitch_username="cleanup_test_user",
            api_token=uuid.uuid4().hex,
            role=UserRole.ORGANIZER,
        )
        db.add(user)
        db.flush()

        race = Race(
            id=race_id,
            name="Cleanup Test Race",
            organizer_id=user_id,
            status=RaceStatus.FINISHED,
            finished_at=datetime.now(UTC) - timedelta(hours=25),
        )
        db.add(race)
        db.flush()

        # Add chat messages
        msg = ChatMessage(
            race_id=race_id,
            channel=ChatChannel.PUBLIC,
            user_id=user_id,
            message="Old message",
        )
        db.add(msg)
        db.commit()

        # Verify message exists
        from sqlalchemy import select

        result = db.execute(select(ChatMessage).where(ChatMessage.race_id == race_id))
        assert len(result.scalars().all()) == 1

    finally:
        db.close()

    # Run cleanup using the async session maker
    from speedfog_racing.database import async_session_maker

    count = await cleanup_old_chat_messages(async_session_maker)
    assert count >= 1

    # Verify message is gone
    db = TestingSessionLocal()
    try:
        from sqlalchemy import select

        result = db.execute(select(ChatMessage).where(ChatMessage.race_id == race_id))
        assert len(result.scalars().all()) == 0
    finally:
        db.close()
```

- [ ] **Step 6: Run tests**

Run: `cd server && uv run pytest tests/test_chat_cleanup.py -v`
Expected: PASS

- [ ] **Step 7: Run linters**

Run: `cd server && uv run ruff check . && uv run ruff format . && uv run mypy speedfog_racing/`

- [ ] **Step 8: Commit**

```bash
git add server/speedfog_racing/services/race_lifecycle.py server/speedfog_racing/api/races.py server/speedfog_racing/services/chat_cleanup.py server/speedfog_racing/main.py server/tests/test_chat_cleanup.py
git commit -m "feat: add Race.finished_at, chat message cleanup background task"
```

---

### Task 8: Frontend WebSocket Types + Race Store

**Files:**

- Modify: `web/src/lib/websocket.ts`
- Modify: `web/src/lib/stores/race.svelte.ts`

- [ ] **Step 1: Add channel field to ChatMessage and add ChatHistoryMessage**

In `web/src/lib/websocket.ts`, update `ChatMessage` (lines 75-84):

```typescript
export interface ChatMessage {
  type: "chat_message";
  channel: "participants" | "public";
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  role: string;
  dominant_trait: string | null;
  message: string;
  timestamp: string;
}

export interface ChatHistoryMessage {
  type: "chat_history";
  channel: "participants" | "public";
  messages: ChatMessage[];
}
```

Update the `ServerMessage` union (lines 86-92):

```typescript
export type ServerMessage =
  | RaceStateMessage
  | LeaderboardUpdateMessage
  | PlayerUpdateMessage
  | RaceStatusChangeMessage
  | SpectatorCountMessage
  | ChatMessage
  | ChatHistoryMessage;
```

Update `VALID_SERVER_MESSAGE_TYPES` (lines 94-101):

```typescript
const VALID_SERVER_MESSAGE_TYPES = new Set([
  "race_state",
  "leaderboard_update",
  "player_update",
  "race_status_change",
  "spectator_count",
  "chat_message",
  "chat_history",
]);
```

Add `onChatHistory` to the options interface. Find the `RaceWebSocketOptions` interface and add:

```typescript
  onChatHistory?: (msg: ChatHistoryMessage) => void;
```

Update `handleMessage` (lines 268-295), add case before default:

```typescript
      case "chat_history":
        this.options.onChatHistory?.(msg);
        break;
```

- [ ] **Step 2: Update race store with dual message arrays**

In `web/src/lib/stores/race.svelte.ts`, update imports (line 8):

```typescript
import {
  createRaceWebSocket,
  type RaceWebSocket,
  type ChatMessage,
  type ChatHistoryMessage,
  type WsParticipant,
  type WsRaceInfo,
  type WsSeedInfo,
} from "$lib/websocket";
```

Replace the single `chatMessages` state (line 18) with:

```typescript
chatMessagesParticipants = $state<ChatMessage[]>([]);
chatMessagesPublic = $state<ChatMessage[]>([]);
```

Update the `connect()` method reset (line 84):

```typescript
this.chatMessagesParticipants = [];
this.chatMessagesPublic = [];
```

Update `onChatMessage` handler (lines 171-173):

```typescript
        onChatMessage: (msg) => {
          if (msg.channel === "participants") {
            this.chatMessagesParticipants = [...this.chatMessagesParticipants, msg];
          } else {
            this.chatMessagesPublic = [...this.chatMessagesPublic, msg];
          }
        },
```

Add `onChatHistory` handler after `onChatMessage`:

```typescript
        onChatHistory: (msg) => {
          if (msg.channel === "participants") {
            this.chatMessagesParticipants = [...msg.messages];
          } else {
            this.chatMessagesPublic = [...msg.messages];
          }
        },
```

Update `disconnect()` method (line 198):

```typescript
this.chatMessagesParticipants = [];
this.chatMessagesPublic = [];
```

- [ ] **Step 3: Run frontend checks**

Run: `cd web && npm run check`
Expected: no type errors

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/websocket.ts web/src/lib/stores/race.svelte.ts
git commit -m "feat: add channel support to frontend WebSocket types and race store"
```

---

### Task 9: Frontend Chat UI (Tabs, Unread, Grayed State)

**Files:**

- Modify: `web/src/lib/components/ChatSidebar.svelte`
- Modify: `web/src/lib/components/ChatPanel.svelte`

- [ ] **Step 1: Update ChatSidebar props and add tab state**

Rewrite `web/src/lib/components/ChatSidebar.svelte`:

```svelte
<script lang="ts">
 import type { ChatMessage } from '$lib/websocket';
 import ChatPanel from './ChatPanel.svelte';

 interface Props {
  messagesParticipants: ChatMessage[];
  messagesPublic: ChatMessage[];
  canSend: boolean;
  collapsed: boolean;
  showParticipants: boolean;
  publicEnabled: boolean;
  activeTab: 'participants' | 'public';
  onSend: (message: string, channel: 'participants' | 'public') => void;
  onToggle: () => void;
  onTabChange: (tab: 'participants' | 'public') => void;
 }

 let {
  messagesParticipants,
  messagesPublic,
  canSend,
  collapsed,
  showParticipants,
  publicEnabled,
  activeTab,
  onSend,
  onToggle,
  onTabChange
 }: Props = $props();

 let lastSeenCount = $state(0);
 let unreadCount = $state(0);
 let unreadParticipants = $state(0);
 let unreadPublic = $state(0);
 let lastSeenParticipants = $state(0);
 let lastSeenPublic = $state(0);

 let activeMessages = $derived(
  activeTab === 'participants' ? messagesParticipants : messagesPublic
 );

 let hasTabs = $derived(showParticipants && publicEnabled !== undefined);
 let totalUnread = $derived(unreadParticipants + unreadPublic);

 // Track unread for collapsed state
 $effect(() => {
  const total = messagesParticipants.length + messagesPublic.length;
  if (!collapsed) {
   lastSeenCount = total;
   unreadCount = 0;
  } else {
   const newCount = total - lastSeenCount;
   unreadCount = newCount > 0 ? newCount : 0;
  }
 });

 // Track per-tab unread
 $effect(() => {
  if (activeTab === 'participants' && !collapsed) {
   lastSeenParticipants = messagesParticipants.length;
   unreadParticipants = 0;
  } else {
   const diff = messagesParticipants.length - lastSeenParticipants;
   unreadParticipants = diff > 0 ? diff : 0;
  }
 });

 $effect(() => {
  if (activeTab === 'public' && !collapsed) {
   lastSeenPublic = messagesPublic.length;
   unreadPublic = 0;
  } else {
   const diff = messagesPublic.length - lastSeenPublic;
   unreadPublic = diff > 0 ? diff : 0;
  }
 });

 function handleSend(message: string) {
  onSend(message, activeTab);
 }
</script>

<aside class="chat-sidebar" class:collapsed>
 {#if collapsed}
  <button class="toggle-btn" onclick={onToggle} title="Open chat">
   <svg
    class="icon"
    width="18"
    height="18"
    viewBox="0 0 24 24"
    fill="none"
    stroke="currentColor"
    stroke-width="2"
    stroke-linecap="round"
    stroke-linejoin="round"
   >
    <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
   </svg>
   {#if unreadCount > 0}
    <span class="unread-badge">{unreadCount > 99 ? '99+' : unreadCount}</span>
   {/if}
  </button>
 {:else}
  <div class="sidebar-content">
   <div class="chat-header">
    {#if showParticipants}
     <div class="tab-bar">
      <button
       class="tab"
       class:active={activeTab === 'participants'}
       onclick={() => onTabChange('participants')}
      >
       Participants
       {#if unreadParticipants > 0 && activeTab !== 'participants'}
        <span class="tab-badge">{unreadParticipants > 99 ? '99+' : unreadParticipants}</span>
       {/if}
      </button>
      <button
       class="tab"
       class:active={activeTab === 'public'}
       class:disabled={!publicEnabled}
       disabled={!publicEnabled}
       onclick={() => publicEnabled && onTabChange('public')}
       title={!publicEnabled ? 'Available after finishing the race' : ''}
      >
       Public
       {#if unreadPublic > 0 && activeTab !== 'public'}
        <span class="tab-badge">{unreadPublic > 99 ? '99+' : unreadPublic}</span>
       {/if}
      </button>
     </div>
    {:else}
     <span class="chat-title">Chat</span>
    {/if}
    <button class="collapse-btn" onclick={onToggle} title="Close chat">
     <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      stroke-width="2"
      stroke-linecap="round"
      stroke-linejoin="round"
     >
      <polyline points="13 6 19 12 13 18" />
      <line x1="7" y1="12" x2="19" y2="12" />
      <line x1="3" y1="4" x2="3" y2="20" />
     </svg>
    </button>
   </div>
   <div class="chat-area">
    <ChatPanel messages={activeMessages} {canSend} onSend={handleSend} />
   </div>
  </div>
 {/if}
</aside>

<style>
 .chat-sidebar {
  position: relative;
  width: 320px;
  flex-shrink: 0;
  background: var(--color-surface);
  border-left: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  transition: width var(--transition);
  overflow: hidden;
 }

 .chat-sidebar.collapsed {
  width: 44px;
 }

 .toggle-btn {
  width: 44px;
  height: 44px;
  margin: 0.5rem auto 0;
  background: none;
  border: none;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--color-text-secondary);
  transition: color var(--transition);
  position: relative;
 }

 .toggle-btn:hover {
  color: var(--color-text);
 }

 .icon {
  flex-shrink: 0;
 }

 .unread-badge {
  position: absolute;
  top: 2px;
  right: 2px;
  min-width: 16px;
  height: 16px;
  background: var(--color-danger);
  color: #fff;
  font-size: 0.55rem;
  font-weight: 700;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 3px;
  pointer-events: none;
 }

 .sidebar-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
 }

 .chat-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 0 0.5rem 0 0;
  border-bottom: 1px solid var(--color-border);
  flex-shrink: 0;
  min-height: 42px;
 }

 .chat-title {
  font-size: var(--font-size-sm);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.05em;
  color: var(--color-text-secondary);
  padding: 0 0.75rem;
 }

 .tab-bar {
  display: flex;
  gap: 0;
  flex: 1;
 }

 .tab {
  flex: 1;
  padding: 0.6rem 0.5rem;
  background: none;
  border: none;
  border-bottom: 2px solid transparent;
  cursor: pointer;
  font-size: var(--font-size-xs);
  font-weight: 600;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--color-text-secondary);
  transition:
   color var(--transition),
   border-color var(--transition);
  position: relative;
 }

 .tab:hover:not(.disabled) {
  color: var(--color-text);
 }

 .tab.active {
  color: var(--color-primary);
  border-bottom-color: var(--color-primary);
 }

 .tab.disabled {
  opacity: 0.35;
  cursor: not-allowed;
 }

 .tab-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 14px;
  height: 14px;
  background: var(--color-danger);
  color: #fff;
  font-size: 0.5rem;
  font-weight: 700;
  border-radius: 7px;
  padding: 0 3px;
  margin-left: 4px;
  vertical-align: middle;
 }

 .collapse-btn {
  background: none;
  border: none;
  cursor: pointer;
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  padding: 0.25rem;
  border-radius: var(--radius-sm);
  transition: color var(--transition);
  flex-shrink: 0;
 }

 .collapse-btn:hover {
  color: var(--color-text);
 }

 .chat-area {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
 }

 @media (max-width: 768px) {
  .chat-sidebar {
   display: none;
  }
 }
</style>
```

- [ ] **Step 2: Run frontend checks**

Run: `cd web && npm run check`
Expected: errors expected because the race page hasn't been updated yet (will fix in Task 10)

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/components/ChatSidebar.svelte
git commit -m "feat: add tab UI to ChatSidebar with per-channel unread badges and grayed state"
```

---

### Task 10: Race Page Integration

**Files:**

- Modify: `web/src/routes/race/[id]/+page.svelte`

- [ ] **Step 1: Add tab state and channel logic**

In `web/src/routes/race/[id]/+page.svelte`, add state variables after `chatCollapsed` (line 73):

```typescript
let chatActiveTab = $state<"participants" | "public">("participants");
```

Add derived values for channel visibility after `myParticipantFinished` (line 284):

```typescript
let hasParticipantsAccess = $derived(
  isOrganizer || auth.isAdmin || isCaster || !!myParticipant,
);
let isParticipantPlaying = $derived(
  !!myParticipant && raceStatus === "running" && !myParticipantFinished,
);
let publicEnabled = $derived(
  !isParticipantPlaying ||
    !myParticipant ||
    isOrganizer ||
    auth.isAdmin ||
    isCaster,
);
let canSendChat = $derived(
  chatActiveTab === "participants"
    ? hasParticipantsAccess
    : auth.isLoggedIn && !isParticipantPlaying,
);
```

- [ ] **Step 2: Add auto-switch effect on finish**

Add an effect to auto-switch to PUBLIC when a participant finishes:

```typescript
let prevFinished = $state(false);
$effect(() => {
  if (myParticipantFinished && !prevFinished) {
    chatActiveTab = "public";
  }
  prevFinished = myParticipantFinished;
});
```

- [ ] **Step 3: Update sendChatMessage to include channel**

Replace `sendChatMessage` (lines 82-84):

```typescript
function sendChatMessage(message: string, channel: "participants" | "public") {
  raceStore.send({ type: "chat", channel, message });
}
```

- [ ] **Step 4: Update ChatSidebar integration**

Replace the ChatSidebar component usage (lines 861-867):

```svelte
 {#if auth.isLoggedIn}
  <ChatSidebar
   messagesParticipants={raceStore.chatMessagesParticipants}
   messagesPublic={raceStore.chatMessagesPublic}
   canSend={canSendChat}
   collapsed={chatCollapsed}
   showParticipants={hasParticipantsAccess}
   {publicEnabled}
   activeTab={hasParticipantsAccess ? chatActiveTab : 'public'}
   onSend={sendChatMessage}
   onToggle={() => (chatCollapsed = !chatCollapsed)}
   onTabChange={(tab) => (chatActiveTab = tab)}
  />
 {/if}
```

- [ ] **Step 5: Run frontend checks and fix any issues**

Run: `cd web && npm run check`
Expected: PASS

Run: `cd web && npm run lint`
Fix any issues.

- [ ] **Step 6: Commit**

```bash
git add web/src/routes/race/[id]/+page.svelte
git commit -m "feat: integrate dual-channel chat with tab visibility and auto-switch on finish"
```

---

### Task 11: End-to-End Verification + Linting

**Files:** All modified files

- [ ] **Step 1: Run all server tests**

Run: `cd server && uv run pytest -v --timeout=30`
Expected: all tests PASS

- [ ] **Step 2: Run server linters**

Run:

```bash
cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy speedfog_racing/
```

Fix any issues.

- [ ] **Step 3: Run frontend checks**

Run:

```bash
cd web && npm run check && npm run lint
```

Fix any issues.

- [ ] **Step 4: Verify no import cycles or missing imports**

Run: `cd server && uv run python -c "from speedfog_racing.main import app; print('OK')"`
Expected: "OK"

- [ ] **Step 5: Final commit if any fixes were needed**

```bash
git add -u
git commit -m "fix: resolve linting and type errors from chat channels implementation"
```
