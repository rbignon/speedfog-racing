# Caster Self-Join & Twitch Live Detection

Date: 2026-02-28

## Summary

Two complementary features:

- **Feature A**: Any authenticated user can self-join/leave as a caster on a race
- **Feature B**: Auto-detect Twitch live status for participants and casters via polling

## Feature A: Caster Self-Join / Self-Leave

### Endpoints

- `POST /api/races/{id}/cast-join` — self-join as caster
  - Auth required
  - Race must be SETUP or RUNNING
  - Mutual exclusion enforced (cannot be a participant)
  - 409 if already a caster
  - Returns updated `RaceDetail`

- `POST /api/races/{id}/cast-leave` — self-remove as caster
  - Auth required
  - 404 if not a caster on this race
  - Returns updated `RaceDetail`

### Rules

- No open registration requirement — any authenticated user can cast any race
- Caster/participant mutual exclusion stays in place
- Organizer can still add/remove casters (existing endpoints unchanged)

### Frontend

- Button "Cast this race" in sidebar, below `CasterList`
  - Visible when: user is authenticated + not a participant + not already a caster
- When user is a caster: "(You)" badge on their entry + inline "Leave" button
- Same UX pattern as `ParticipantCard` with `canRemove`/`onRemove`

## Feature B: Twitch Live Auto-Detection

### Twitch App Token

- Client credentials flow (`POST https://id.twitch.tv/oauth2/token` with `grant_type=client_credentials`)
- No scope needed for `GET /helix/streams`
- `TWITCH_CLIENT_ID` and `TWITCH_CLIENT_SECRET` already in config
- New helper `get_app_access_token()` in `auth.py` — cached in memory, refreshed on expiry

### Polling Service

- New module: `server/speedfog_racing/services/twitch_live.py`
- `TwitchLiveService`:
  - In-memory dict `{twitch_username: is_live}` per active race
  - `asyncio.Task` started at app lifespan, polls every 60s
  - Collects all participants + casters from SETUP/RUNNING races
  - Batch query `GET /helix/streams?user_login=...` (up to 100 per request)
  - On status change → broadcast via WebSocket (`player_update` or `caster_update`)
  - Graceful shutdown on app teardown

### Rate Limiting

- App token: 800 req/min
- 1 request covers 100 users
- Even 10 active races of 100 players = ~10 req/min — well within limits

### WebSocket Schema Changes

- `ParticipantInfo`: add `is_live: bool` (default `false`) and `stream_url: str | None`
- Caster info (new or enriched schema): add `is_live: bool` and `stream_url: str | None`
- `stream_url` = `https://twitch.tv/{twitch_username}`

### Frontend

- Red "LIVE" badge in:
  - `ParticipantCard` (leaderboard) — clickable, opens Twitch in new tab
  - `CasterList` (caster section) — same behavior
  - `/overlay/race/[id]/leaderboard` — visible in OBS overlay
- `raceStore` updates live status on `player_update` / `caster_update` messages

## What Does NOT Change

- Overlay DAG remains `MetroDagFull` (used by pure casters and spectators)
- Participants still see `MetroDagProgressive` on their race page
- Caster/Participant DB models stay structurally unchanged
- `is_live` is ephemeral (in-memory), not stored in DB
