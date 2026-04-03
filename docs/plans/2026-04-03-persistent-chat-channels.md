# Persistent Chat with Dual Channels

## Overview

Replace the current in-memory, single-channel race chat with two persistent chat channels: a private **Participants** channel for race coordination, and a **Public** channel for open discussion that is hidden from players still in-game to prevent spoilers.

## Motivation

Two distinct usage patterns exist today:

1. Pre-race coordination (players checking readiness)
2. Post-race discussion between finished players

In the second case, players still racing can see the messages, which spoils their experience. Additionally, messages are lost on page reload, late joins, or server restart.

## Chat Channels

### Participants Channel

Private channel for race participants, organizer, casters, and admins. Not visible to spectators at all.

Used for: pre-race coordination, technical issue communication during the race, participant-only discussion.

Active from SETUP through FINISHED.

### Public Channel

Open channel for all logged-in users. Hidden from participants who are still playing during RUNNING status, to prevent spoilers.

Used for: spectator discussion, post-finish cross-talk between spectators and finished players.

Active at all times during the race lifecycle.

## Access Matrix

| Role / Status              | PARTICIPANTS | PUBLIC               |
| -------------------------- | ------------ | -------------------- |
| Participant (SETUP)        | read + write | read + write         |
| Participant (playing)      | read + write | blocked (tab grayed) |
| Participant (finished/DNF) | read + write | read + write         |
| Organizer                  | read + write | read + write         |
| Caster                     | read + write | read + write         |
| Admin                      | read + write | read + write         |
| Spectator (logged in)      | invisible    | read + write         |
| Spectator (not logged in)  | invisible    | invisible            |

## Data Model

New table `chat_message`:

```python
class ChatChannel(str, enum.Enum):
    PARTICIPANTS = "participants"
    PUBLIC = "public"

class ChatMessage(Base):
    __tablename__ = "chat_message"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    race_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("race.id", ondelete="CASCADE"), index=True)
    channel: Mapped[ChatChannel]
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    message: Mapped[str] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(default=lambda: datetime.now(UTC))

    race: Mapped["Race"] = relationship()
    user: Mapped["User"] = relationship()
```

Composite index on `(race_id, channel, created_at)` for history queries.

The `role` and `dominant_trait` fields are NOT stored in the message. They are resolved at broadcast time from the current user state (existing behavior). For history replay, they are resolved at load time. This avoids stale data if a user's role or trait changes.

## WebSocket Protocol

### Client to Server

Extend the existing `chat` message with a `channel` field:

```json
{ "type": "chat", "channel": "participants", "message": "hello" }
```

The server validates that the sender has write access to the requested channel. Invalid messages are silently ignored (consistent with current behavior).

### Server to Client: chat_message

Existing `ChatBroadcastMessage` extended with `channel`:

```json
{
  "type": "chat_message",
  "channel": "participants",
  "username": "player1",
  "display_name": "Player One",
  "avatar_url": "https://...",
  "role": "participant",
  "dominant_trait": "rusher",
  "message": "hello",
  "timestamp": "2026-04-03T12:00:00Z"
}
```

**Server-side broadcast filtering** (messages are never sent to unauthorized connections):

- **PARTICIPANTS channel**: broadcast only to participants, organizer, casters, admins
- **PUBLIC channel during SETUP/FINISHED**: broadcast to all authenticated connections
- **PUBLIC channel during RUNNING**: broadcast to all authenticated connections EXCEPT participants with status "playing"

### Server to Client: chat_history

New message sent after authentication (after `auth_ok` for spectators, after mod auth):

```json
{
  "type": "chat_history",
  "channel": "participants",
  "messages": [
    /* array of ChatBroadcastMessage objects */
  ]
}
```

One `chat_history` message per channel the user has access to. Sent on initial connection to hydrate the chat.

### Participant Finish Transition

When a participant finishes:

1. Server sends `chat_history` for the PUBLIC channel (catch-up on missed messages)
2. From this point, the participant's connection is included in PUBLIC channel broadcasts

## Message Cleanup

Background asyncio task started in the FastAPI lifespan, running every hour:

```sql
DELETE FROM chat_message
WHERE race_id IN (
    SELECT id FROM race
    WHERE status = 'finished'
    AND finished_at < now() - interval '24 hours'
)
```

Uses the existing `finished_at` field on the `Race` model. Logs the number of deleted messages.

## Frontend

### Tab UI

Two tabs in the existing chat sidebar panel:

```
┌─────────────────────────────┐
│ [Participants] [Public •2]  │  <- tabs with unread badge on inactive tab
├─────────────────────────────┤
│                             │
│  messages for active tab    │
│                             │
├─────────────────────────────┤
│ [____message input____] [>] │
└─────────────────────────────┘
```

**Tab visibility rules:**

| Situation                      | Tabs shown                                                 |
| ------------------------------ | ---------------------------------------------------------- |
| Spectator (not logged in)      | No chat at all                                             |
| Spectator (logged in)          | PUBLIC only (no tab bar, just the chat)                    |
| Participant (SETUP)            | PARTICIPANTS + PUBLIC (both active)                        |
| Participant (RUNNING, playing) | PARTICIPANTS + PUBLIC (grayed, not clickable)              |
| Participant (finished/DNF)     | PARTICIPANTS + PUBLIC (both active, auto-switch to PUBLIC) |
| Organizer / Caster / Admin     | PARTICIPANTS + PUBLIC (both active)                        |

When only one tab is visible, the tab bar is hidden entirely.

### Unread Badge

Unread message counter on the inactive tab. Incremented when a message arrives on a channel that is not currently displayed. Reset when switching to that tab. Same logic as the existing unread badge on the collapsed sidebar toggle button.

### Auto-switch on Finish

When a participant finishes:

1. PUBLIC tab becomes active (un-grayed)
2. Chat receives `chat_history` for PUBLIC channel
3. Auto-switch to the PUBLIC tab
4. PARTICIPANTS tab shows unread badge if messages continue there

### Collapsed Sidebar

Single icon with combined unread count (sum of both channels). On click, opens sidebar on the last active tab (or the tab with unread messages if only one has any). No change to the collapsed layout regardless of role.

### Store Changes

`RaceStore` maintains two separate message arrays:

```typescript
chatMessagesParticipants = $state<ChatMessage[]>([]);
chatMessagesPublic = $state<ChatMessage[]>([]);
```

`chat_history` hydrates the corresponding array. Real-time `chat_message` events are appended to the correct array based on the `channel` field.

## Out of Scope

- Rate limiting on chat messages (premature at current community size)
- Content moderation / filtering
- Chat in training mode
- Message editing or deletion by users
