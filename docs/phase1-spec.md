# Phase 1 Specification - MVP

**Objective:** A functional race from end to end - organizer creates race, players download zips, race runs with live leaderboard.

## 1. Server Setup

### 1.1 Project Structure

```
server/
├── speedfog_racing/
│   ├── __init__.py          # Version
│   ├── main.py              # FastAPI app
│   ├── config.py            # Settings from env
│   ├── database.py          # SQLAlchemy async setup
│   ├── models.py            # DB models
│   ├── auth.py              # Twitch OAuth helpers
│   │
│   ├── api/
│   │   ├── __init__.py      # Router aggregation
│   │   ├── auth.py          # /api/auth/*
│   │   ├── races.py         # /api/races/*
│   │   └── users.py         # /api/users/*
│   │
│   ├── websocket/
│   │   ├── __init__.py
│   │   ├── manager.py       # RaceRoom, ConnectionManager
│   │   └── mod.py           # Mod WebSocket handler
│   │
│   └── services/
│       ├── __init__.py
│       ├── race_service.py  # Race business logic
│       └── seed_service.py  # Pool & zip generation
│
├── alembic/
│   ├── versions/
│   └── env.py
├── alembic.ini
├── pyproject.toml
├── .env.example
└── tests/
```

### 1.2 Dependencies

```toml
# pyproject.toml
[project]
name = "speedfog-racing"
version = "0.1.0"
requires-python = ">=3.11"
dependencies = [
    "fastapi>=0.109",
    "uvicorn[standard]>=0.27",
    "sqlalchemy[asyncio]>=2.0",
    "asyncpg>=0.29",
    "alembic>=1.13",
    "httpx>=0.26",
    "pydantic>=2.5",
    "pydantic-settings>=2.1",
    "python-multipart>=0.0.6",
    "websockets>=12.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-asyncio>=0.23",
    "ruff>=0.1",
]
```

### 1.3 Configuration

```python
# config.py
from pydantic_settings import BaseSettings

class Settings(BaseSettings):
    # Database
    database_url: str = "postgresql+asyncpg://localhost/speedfog_racing"

    # Twitch OAuth
    twitch_client_id: str
    twitch_client_secret: str
    twitch_redirect_uri: str

    # App
    secret_key: str
    base_url: str = "http://localhost:8000"
    websocket_url: str = "ws://localhost:8000"

    # Seeds
    seeds_pool_dir: str = "/data/seeds"
    speedfog_path: str  # Path to speedfog repo

    class Config:
        env_file = ".env"
```

### 1.4 Database Models

```python
# models.py
from sqlalchemy import Column, String, Integer, DateTime, ForeignKey, JSON, Enum, Boolean
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship
import uuid
import enum

class UserRole(enum.Enum):
    USER = "user"
    ADMIN = "admin"

class RaceStatus(enum.Enum):
    DRAFT = "draft"
    OPEN = "open"
    COUNTDOWN = "countdown"
    RUNNING = "running"
    FINISHED = "finished"

class ParticipantStatus(enum.Enum):
    REGISTERED = "registered"
    READY = "ready"
    PLAYING = "playing"
    FINISHED = "finished"
    ABANDONED = "abandoned"

class User(Base):
    __tablename__ = "users"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    twitch_id = Column(String, unique=True, nullable=False)
    twitch_username = Column(String, nullable=False)
    twitch_display_name = Column(String)
    twitch_avatar_url = Column(String)
    api_token = Column(String, unique=True, nullable=False)
    role = Column(Enum(UserRole), default=UserRole.USER)
    created_at = Column(DateTime, server_default=func.now())

class Seed(Base):
    __tablename__ = "seeds"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    seed_number = Column(Integer, nullable=False)
    pool_name = Column(String, nullable=False)  # "standard", "sprint", etc.
    graph_json = Column(JSON, nullable=False)
    total_layers = Column(Integer, nullable=False)
    folder_path = Column(String, nullable=False)  # Path in pool
    consumed = Column(Boolean, default=False)
    created_at = Column(DateTime, server_default=func.now())

class Race(Base):
    __tablename__ = "races"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    name = Column(String, nullable=False)
    organizer_id = Column(UUID, ForeignKey("users.id"), nullable=False)
    seed_id = Column(UUID, ForeignKey("seeds.id"))
    status = Column(Enum(RaceStatus), default=RaceStatus.DRAFT)
    config = Column(JSON, default={})  # show_finished_names, max_participants
    scheduled_start = Column(DateTime)  # UTC
    created_at = Column(DateTime, server_default=func.now())

    organizer = relationship("User")
    seed = relationship("Seed")
    participants = relationship("Participant", back_populates="race")

class Participant(Base):
    __tablename__ = "participants"

    id = Column(UUID, primary_key=True, default=uuid.uuid4)
    race_id = Column(UUID, ForeignKey("races.id"), nullable=False)
    user_id = Column(UUID, ForeignKey("users.id"), nullable=False)
    mod_token = Column(String, unique=True, nullable=False)
    current_zone = Column(String)
    current_layer = Column(Integer, default=0)
    igt_ms = Column(Integer, default=0)
    death_count = Column(Integer, default=0)
    finished_at = Column(DateTime)
    status = Column(Enum(ParticipantStatus), default=ParticipantStatus.REGISTERED)

    race = relationship("Race", back_populates="participants")
    user = relationship("User")
```

---

## 2. API Endpoints

### 2.1 Auth

```
GET /api/auth/twitch
    -> Redirect to Twitch OAuth

GET /api/auth/callback?code=XXX&state=XXX
    -> Exchange code, create/update user, return JWT or session
    -> Redirect to frontend with token

GET /api/auth/me
    Headers: Authorization: Bearer <token>
    -> Return current user info
```

### 2.2 Races

```
POST /api/races
    Headers: Authorization: Bearer <token>
    Body: { name: string, pool_name: string, config: object }
    -> Create race, assign random seed from pool
    -> Return race details

GET /api/races
    -> List races (filterable by status)

GET /api/races/{race_id}
    -> Race details with participants

POST /api/races/{race_id}/participants
    Headers: Authorization: Bearer <token>
    Body: { twitch_username: string }
    -> Add participant (organizer only)
    -> If user doesn't exist, create invite token

DELETE /api/races/{race_id}/participants/{participant_id}
    -> Remove participant (organizer only)

POST /api/races/{race_id}/generate-zips
    Headers: Authorization: Bearer <token>
    -> Generate personalized zips for all participants
    -> Return download URLs

GET /api/races/{race_id}/download/{mod_token}
    -> Download personalized zip for participant

POST /api/races/{race_id}/start
    Headers: Authorization: Bearer <token>
    Body: { scheduled_start: datetime }
    -> Set scheduled_start, change status to COUNTDOWN
```

### 2.3 Invites

```
GET /api/invite/{token}
    -> Get invite info (race name, etc.)

POST /api/invite/{token}/accept
    Headers: Authorization: Bearer <token>
    -> Accept invite, add user as participant
```

---

## 3. WebSocket Protocol

### 3.1 Mod Connection

```
WS /ws/mod/{race_id}

# Auth (first message)
-> { "type": "auth", "mod_token": "xxx" }
<- { "type": "auth_ok",
     "race": { "name", "status", "scheduled_start" },
     "seed": { "total_layers" },
     "participants": [...] }
<- { "type": "auth_error", "message": "..." }

# Ready signal
-> { "type": "ready" }

# Status updates (periodic, every ~1 sec)
-> { "type": "status_update",
     "igt_ms": 123456,
     "current_zone": "zone_id",
     "death_count": 5 }
     # Note: current_layer removed - server computes from zone_entered

# Zone change
-> { "type": "zone_entered",
     "from_zone": "zone_a",
     "to_zone": "zone_b",
     "igt_ms": 98765 }

# Finish
-> { "type": "finished", "igt_ms": 654321 }

# Server broadcasts
<- { "type": "race_start" }
<- { "type": "leaderboard_update", "participants": [...] }
     # Participants pre-sorted: finished (by IGT asc), then playing (by layer desc)
<- { "type": "race_status_change", "status": "running" }
<- { "type": "player_update", "player": {...} }  # Single player optimization
```

### 3.2 Spectator Connection

```
WS /ws/race/{race_id}

# No auth required (public)

# Initial state
<- { "type": "race_state",
     "race": { "name", "status", "scheduled_start" },
     "seed": { "graph_json", "total_layers" },
     "participants": [...] }

# Updates
<- { "type": "player_update", "player": {...} }
<- { "type": "race_status_change", "status": "running" }
```

---

## 4. Frontend (SvelteKit)

### 4.1 Routes

```
/                           # Home - list of races
/auth/callback              # Twitch OAuth callback
/race/new                   # Create race form
/race/{id}                  # Race view (spectator/organizer/player)
/race/{id}/manage           # Manage race (organizer only)
/invite/{token}             # Accept invite
```

### 4.2 Key Components

```
src/lib/
├── api.ts                  # REST API client
├── websocket.ts            # WebSocket client with reconnect
├── stores/
│   ├── auth.ts             # User session store
│   └── race.ts             # Current race state store
└── components/
    ├── Leaderboard.svelte  # Sorted participant list
    ├── RaceStatus.svelte   # Status badge + countdown
    └── ParticipantRow.svelte
```

### 4.3 Pages

**Home `/`:**

- List of open/running races
- "Create Race" button (if logged in)
- Login with Twitch button

**Create Race `/race/new`:**

- Name input
- Pool selection (show available count)
- Create button -> redirect to manage page

**Race View `/race/{id}`:**

- Left sidebar: Leaderboard
- Center: Race info (name, status, countdown)
- Organizer: link to manage page
- Player: download button if registered

**Manage Race `/race/{id}/manage`:**

- Add participants by Twitch username
- List participants with remove button
- "Generate Zips" button
- "Start Race" button with datetime picker

---

## 5. Mod (Rust Fork)

### 5.1 Fork Strategy

1. Clone er-fog-vizu/mod as starting point
2. Remove launcher/ directory
3. Adapt protocol in core/protocol.rs
4. Simplify tracker to race-focused logic
5. Update overlay UI for race display

### 5.2 Key Changes

**protocol.rs:**

```rust
#[derive(Serialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ClientMessage {
    Auth { mod_token: String },
    Ready,
    StatusUpdate {
        igt_ms: u32,
        current_zone: String,
        death_count: u32,
        // Note: current_layer removed - server computes from zone_entered events
    },
    ZoneEntered {
        from_zone: String,
        to_zone: String,
        igt_ms: u32,
    },
    Finished { igt_ms: u32 },
}

#[derive(Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum ServerMessage {
    AuthOk { race: RaceInfo, seed: SeedInfo, participants: Vec<Participant> },
    AuthError { message: String },
    RaceStart,
    LeaderboardUpdate { participants: Vec<Participant> },  // Pre-sorted by server
    RaceStatusChange { status: String },
    PlayerUpdate { player: Participant },
}
```

**Overlay (Phase 1 - minimal):**

- Zone name + IGT + death count
- Connection status indicator
- Basic leaderboard (name + layer + status)
- F9 hotkey to toggle visibility

### 5.4 Hotkey System

The mod must implement keyboard input handling for the F9 toggle:

```rust
// Required functionality:
// 1. Read keyboard state each frame
// 2. Detect F9 key press (with debounce to avoid rapid toggling)
// 3. Toggle show_ui boolean
// 4. Respect the configured key from config.keybindings.toggle_ui

// Can be ported from upstream er-fog-vizu/mod hotkey.rs
```

### 5.5 Zone Change Detection

The mod must track zone changes properly:

```rust
// Required functionality:
// 1. Store previous_zone on each frame
// 2. When current_zone != previous_zone:
//    - Send zone_entered { from_zone: previous_zone, to_zone: current_zone, igt_ms }
//    - Update previous_zone = current_zone
// 3. Initialize previous_zone on first zone read (don't send zone_entered for initial zone)
```

### 5.6 Race Finish Detection

The mod must detect when the player completes the race:

```rust
// Phase 1 approach (simple):
// - Detect when player enters a designated "finish zone" (configurable or from seed info)
// - Or: detect specific game event (boss defeat animation/flag)
//
// Send: finished { igt_ms }
// Then stop sending status_update (or mark as finished locally)
```

**Note:** Exact finish detection mechanism TBD based on what's readable from game memory. May require Phase 2 custom EMEVD events for precise detection.

### 5.3 Config

```toml
# speedfog_race.toml
[server]
url = "wss://speedfog-racing.example.com"
mod_token = "PLAYER_TOKEN_HERE"
race_id = "RACE_UUID_HERE"

[overlay]
enabled = true
font_size = 16

[keybindings]
toggle_ui = "f9"
```

---

## 6. Seed Pool Management

### 6.1 Initial Setup (Manual)

For Phase 1, use a single "standard" pool:

```
/data/seeds/
└── standard/
    ├── config.toml          # SpeedFog config for this pool
    ├── available/
    │   ├── seed_123456/
    │   │   ├── mod/
    │   │   ├── ModEngine/
    │   │   ├── graph.json
    │   │   └── launch_speedfog.bat
    │   └── seed_789012/
    └── consumed/
```

### 6.2 Pool Scanner

```python
# services/seed_service.py

async def scan_pool(pool_name: str = "standard"):
    """Scan pool directory and sync with database."""
    pool_dir = Path(settings.seeds_pool_dir) / pool_name / "available"

    for seed_dir in pool_dir.iterdir():
        if not seed_dir.is_dir():
            continue

        seed_number = int(seed_dir.name.split("_")[1])

        # Check if already in DB
        existing = await get_seed_by_number(seed_number)
        if existing:
            continue

        # Load graph.json
        graph = json.load(open(seed_dir / "graph.json"))

        # Create DB entry
        seed = Seed(
            seed_number=seed_number,
            pool_name=pool_name,
            graph_json=graph,
            total_layers=graph["total_layers"],
            folder_path=str(seed_dir),
        )
        db.add(seed)
```

### 6.3 Zip Generation

```python
async def generate_player_zip(race: Race, participant: Participant) -> Path:
    """Generate personalized zip for a participant."""
    seed_dir = Path(race.seed.folder_path)

    # Create temp directory
    temp_dir = Path(tempfile.mkdtemp())
    player_dir = temp_dir / f"speedfog_{race.seed.seed_number}"

    # Copy seed contents
    shutil.copytree(seed_dir, player_dir)

    # Add mod DLL (from our assets)
    shutil.copy(ASSETS_DIR / "speedfog_race.dll", player_dir)

    # Create config with player's token
    config = {
        "server": {
            "url": settings.websocket_url,
            "mod_token": participant.mod_token,
            "race_id": str(race.id),
        },
        "overlay": {"enabled": True, "font_size": 16},
        "keybindings": {"toggle_ui": "f9"},
    }

    with open(player_dir / "speedfog_race.toml", "w") as f:
        toml.dump(config, f)

    # Create zip
    zip_path = ZIPS_DIR / f"{race.id}_{participant.user.twitch_username}.zip"
    shutil.make_archive(str(zip_path.with_suffix("")), "zip", player_dir)

    # Cleanup
    shutil.rmtree(temp_dir)

    return zip_path
```

---

## 7. Implementation Order

### Step 1: Server Foundation ✅

- [x] Create pyproject.toml with dependencies
- [x] Setup FastAPI app skeleton
- [x] Configure Pydantic settings
- [x] Setup SQLAlchemy async with PostgreSQL
- [x] Create Alembic migrations
- [x] Implement database models

### Step 2: Twitch Auth ✅

- [x] Implement OAuth flow (redirect, callback)
- [x] User creation/update on login
- [x] API token generation
- [x] Auth middleware/dependency

### Step 3: Seed Pool (Basic) ✅

- [x] Pool scanner service
- [x] Assign seed to race
- [x] Seed service with get available / mark consumed

### Step 4: Race CRUD ✅

- [x] Create race endpoint (with seed assignment)
- [x] List races endpoint
- [x] Get race details endpoint
- [x] Add/remove participants

### Step 5: Seed Pool (Zip Generation) ✅

- [x] Zip generation service
- [x] Download endpoint

### Step 6: Frontend Foundation ✅

- [x] Setup SvelteKit project
- [x] Implement API client
- [x] Create auth store
- [x] Twitch login flow
- [x] Home page with race list

### Step 7: Race Management UI ✅

- [x] Create race form
- [x] Race detail page
- [x] Manage page (add participants)

### Step 8: WebSocket - Server ✅

- [x] Connection manager
- [x] Mod handler (auth, status updates)
- [x] Leaderboard calculation
- [x] Broadcast to spectators

### Step 9: WebSocket - Frontend ✅

- [x] WebSocket client with reconnect
- [x] Race state store
- [x] Live leaderboard component

### Step 10: Mod Fork ✅

- [x] Fork er-fog-vizu/mod
- [x] Strip launcher code
- [x] Adapt protocol (removed current_layer - server-computed)
- [x] Basic overlay (zone + IGT + leaderboard)
- [x] **Hotkey system** - Full keyboard input with F9 toggle, configurable keybindings
- [x] **Zone change tracking** - Proper zone_entered with from_zone, initial zone handled
- [x] **Race finish detection** - Placeholder with finished_sent flag (detection mechanism TBD Phase 2)
- [ ] Build and test injection (requires Windows/MSVC)

### Step 11: Integration Testing ✅

- [x] End-to-end race flow (3-player complete race with leaderboard verification)
- [x] Multi-player simulation (sequential connections to avoid WebSocket threading issues)
- [x] Error handling (invalid auth, malformed JSON, duplicate connection, unknown message types)

---

## 8. Success Criteria

Phase 1 is complete when:

1. **Auth:** User can login with Twitch
2. **Create:** Organizer can create a race and add participants
3. **Download:** Participants can download their personalized zip
4. **Play:** Mod connects, sends updates, receives leaderboard
5. **Spectate:** Web page shows live leaderboard
6. **Finish:** Race completes when all players finish or abandon

---

## 9. Out of Scope (Phase 1)

- DAG visualization (Phase 2)
- OBS overlays (Phase 2)
- Multi-pool selection (Phase 2)
- Countdown synchronization (Phase 2)
- Admin dashboard (Phase 2)
- Full overlay UI in mod (Phase 2)
