# Step 4: Race CRUD - Design

**Date:** 2026-02-04
**Status:** Approved

## Overview

Implement race management endpoints: create, list, get details, manage participants, and start race.

## Endpoints

### Race Endpoints

```
POST /api/races
    Auth: Required
    Body: { name: string, pool_name?: string, config?: object }
    → Creates race, assigns seed from pool
    → Response: RaceResponse

GET /api/races
    Auth: Optional
    Query: ?status=open,running (optional, CSV list)
    → List races, filterable by status
    → Response: { races: RaceResponse[] }

GET /api/races/{race_id}
    Auth: Optional
    → Details with participants
    → Response: RaceDetailResponse

POST /api/races/{race_id}/participants
    Auth: Required (organizer only)
    Body: { twitch_username: string }
    → If user exists: create Participant
    → If user doesn't exist: create Invite
    → Response: { participant?: ..., invite?: ... }

DELETE /api/races/{race_id}/participants/{participant_id}
    Auth: Required (organizer only)
    → Remove participant
    → Response: 204 No Content

POST /api/races/{race_id}/start
    Auth: Required (organizer only)
    Body: { scheduled_start: datetime }
    → Set status to COUNTDOWN, set scheduled_start
    → Response: RaceResponse
```

### Invite Endpoints

```
GET /api/invite/{token}
    Auth: None
    → Public info: race name, organizer, status
    → Response: InviteInfoResponse

POST /api/invite/{token}/accept
    Auth: Required
    → Validates invite, creates Participant
    → Response: { participant: ..., race_id: ... }
```

## Invite Flow

1. Organizer adds "player123" (no account) → invite created with token
2. Organizer shares `/invite/{token}` link to player
3. Player clicks → page asks to login with Twitch
4. After Twitch auth → invite validated, participant created, redirect to race

## Pydantic Schemas

```python
# Requests
class CreateRaceRequest(BaseModel):
    name: str
    pool_name: str = "standard"
    config: dict[str, Any] = {}

class AddParticipantRequest(BaseModel):
    twitch_username: str

class StartRaceRequest(BaseModel):
    scheduled_start: datetime

# Responses
class UserResponse(BaseModel):
    id: UUID
    twitch_username: str
    twitch_display_name: str | None
    twitch_avatar_url: str | None

class ParticipantResponse(BaseModel):
    id: UUID
    user: UserResponse
    status: ParticipantStatus
    current_layer: int
    igt_ms: int
    death_count: int

class RaceResponse(BaseModel):
    id: UUID
    name: str
    organizer: UserResponse
    status: RaceStatus
    pool_name: str | None
    scheduled_start: datetime | None
    created_at: datetime
    participant_count: int

class RaceDetailResponse(RaceResponse):
    seed_total_layers: int | None
    participants: list[ParticipantResponse]

class InviteInfoResponse(BaseModel):
    race_name: str
    organizer_name: str
    race_status: RaceStatus
```

## Files to Create/Modify

**Create:**

- `server/speedfog_racing/schemas.py` - all Pydantic schemas
- `server/speedfog_racing/api/invites.py` - invite endpoints
- `server/tests/test_races.py`
- `server/tests/test_invites.py`

**Modify:**

- `server/speedfog_racing/api/races.py` - implement endpoints
- `server/speedfog_racing/api/__init__.py` - add invites router

## Tests

1. **Race creation:**
   - Creates race with seed assigned
   - Requires authentication
   - Returns error if no seeds available

2. **Race listing:**
   - Lists all races
   - Filters by status
   - Works without auth

3. **Race details:**
   - Returns race with participants
   - Returns 404 for unknown race

4. **Participant management:**
   - Adds existing user as participant
   - Creates invite for unknown user
   - Only organizer can add/remove
   - Cannot add duplicate participant

5. **Race start:**
   - Sets scheduled_start and status
   - Only organizer can start
   - Cannot start already running race

6. **Invites:**
   - Get invite info without auth
   - Accept invite requires auth
   - Cannot accept already used invite
   - Cannot accept invite for finished race
