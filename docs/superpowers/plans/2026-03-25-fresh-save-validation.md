# Fresh Save Validation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent players from corrupting race/training data by loading a pre-existing save instead of starting a New Game.

**Architecture:** Server-side IGT gate on the READY-to-PLAYING transition (race) and first zone_history initialization (training). Reuses existing `error` message type with human-readable text. One-line mod change to surface error messages on overlay.

**Tech Stack:** Python/FastAPI (server), Rust (mod), pytest (tests)

**Spec:** `docs/plans/2026-03-25-fresh-save-validation.md`

---

## Task 1: Add MAX_FRESH_IGT_MS constant and IGT gate in race handle_status_update

**Files:**

- Modify: `server/speedfog_racing/websocket/common.py:18-20` (add constant)
- Modify: `server/speedfog_racing/websocket/mod.py:372-422` (add IGT gate)
- Test: `server/tests/test_integration.py` (add test)

- [ ] **Step 1: Write the failing test for stale save rejection**

Add to `server/tests/test_integration.py` after the existing `test_status_update_transitions_to_playing_with_start_zone` test:

```python
def test_stale_save_rejected_on_status_update(
    integration_client, race_with_participants, integration_db
):
    """status_update with high IGT (stale save) should be rejected, participant stays READY."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Connect, auth, send ready
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    # Start the race
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    # Send status_update with stale IGT (60 seconds)
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_status_update(igt_ms=60_000, death_count=0)
        resp = mod0.receive()
        assert resp["type"] == "error"
        assert "New Game" in resp["message"]

    # Verify participant is still READY (not transitioned to PLAYING)
    async def check_db():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.status, p.zone_history

    status, history = asyncio.run(check_db())
    assert status == ParticipantStatus.READY
    assert history is None or len(history) == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_integration.py::test_stale_save_rejected_on_status_update -v`
Expected: FAIL (no IGT gate yet, participant transitions to PLAYING)

- [ ] **Step 3: Add constant and implement IGT gate**

In `server/speedfog_racing/websocket/common.py`, add after line 20 (`MOD_AUTH_TIMEOUT`):

```python
MAX_FRESH_IGT_MS = 15_000  # 15s: fresh save reaches first load screen at ~3-5s
```

In `server/speedfog_racing/websocket/mod.py`:

- Add `MAX_FRESH_IGT_MS` to the imports from `common`.
- Add a `stale_save_warned` parameter to `handle_status_update` (a `set[uuid.UUID]` passed from `handle_mod_websocket`).
- In `handle_mod_websocket`, create `stale_save_warned: set[uuid.UUID] = set()` before the message loop and pass it to `handle_status_update`.
- Insert the IGT gate **before** the `igt_ms` write (before current line 401), after the countdown check (line 399):

```python
        # Gate: reject stale saves (pre-existing save with high IGT)
        igt_ms_val = msg.get("igt_ms")
        if (
            isinstance(igt_ms_val, int)
            and participant.status == ParticipantStatus.READY
            and igt_ms_val > MAX_FRESH_IGT_MS
        ):
            if participant_id not in stale_save_warned:
                logger.warning(
                    "Rejected stale save: participant=%s igt_ms=%d",
                    participant_id,
                    igt_ms_val,
                )
                stale_save_warned.add(participant_id)
            else:
                logger.debug(
                    "Rejected stale save (repeat): participant=%s igt_ms=%d",
                    participant_id,
                    igt_ms_val,
                )
            await send_error(websocket, "Please start a New Game to race")
            return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && uv run pytest tests/test_integration.py::test_stale_save_rejected_on_status_update -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add server/speedfog_racing/websocket/common.py server/speedfog_racing/websocket/mod.py server/tests/test_integration.py
git commit -m "feat: reject stale saves on READY-to-PLAYING transition (IGT gate)"
```

## Task 2: Test self-healing (fresh save after stale rejection)

**Files:**

- Test: `server/tests/test_integration.py` (add test)

- [ ] **Step 1: Write the self-healing test**

Add after the previous test:

```python
def test_stale_save_self_heals_on_new_game(
    integration_client, race_with_participants, integration_db
):
    """After stale save rejection, a fresh save (low IGT) should succeed."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Connect, auth, send ready, start race
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # First: stale save rejected
        mod0.send_status_update(igt_ms=60_000, death_count=0)
        resp = mod0.receive()
        assert resp["type"] == "error"

        # Second: player starts New Game, IGT resets
        mod0.send_status_update(igt_ms=500, death_count=0)
        resp = mod0.receive()
        assert resp["type"] == "leaderboard_update"  # READY->PLAYING broadcast

    # Verify PLAYING in DB
    async def check_db():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.status

    status = asyncio.run(check_db())
    assert status == ParticipantStatus.PLAYING
```

- [ ] **Step 2: Run test to verify it passes**

Run: `cd server && uv run pytest tests/test_integration.py::test_stale_save_self_heals_on_new_game -v`
Expected: PASS (implementation from Task 1 already handles this)

- [ ] **Step 3: Commit**

```bash
git add server/tests/test_integration.py
git commit -m "test: verify stale save self-heals when player starts New Game"
```

## Task 3: Tighten participant status guards on event_flag and zone_query

**Files:**

- Modify: `server/speedfog_racing/websocket/mod.py:509-510` (event_flag guard)
- Modify: `server/speedfog_racing/websocket/mod.py:624-625` (zone_query guard)
- Test: `server/tests/test_integration.py` (add tests)

- [ ] **Step 1: Write failing test for event_flag rejection when READY**

```python
def test_event_flag_ignored_when_participant_not_playing(
    integration_client, race_with_participants, integration_db
):
    """event_flag from a READY participant (not yet PLAYING) should be silently dropped."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Ready up and start race
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"
        mod0.send_ready()
        mod0.receive()  # leaderboard_update

    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    # Connect but do NOT send status_update (stays READY), send event_flag
    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        auth_ok = mod0.auth()
        assert auth_ok["type"] == "auth_ok"
        event_ids = auth_ok["seed"]["event_ids"]

        # Send event_flag while still READY
        mod0.send_event_flag(flag_id=event_ids[0], igt_ms=5000)
        # Then transition to PLAYING normally
        mod0.send_status_update(igt_ms=1000, death_count=0)
        resp = mod0.receive()
        assert resp["type"] == "leaderboard_update"
        time.sleep(0.5)

    # Verify zone_history has only the spawn entry (no fog entry from the dropped event_flag)
    async def check_db():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history

    history = asyncio.run(check_db())
    assert history is not None
    assert len(history) == 1  # Only spawn entry, no fog entry
    assert history[0]["type"] == "spawn"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_integration.py::test_event_flag_ignored_when_participant_not_playing -v`
Expected: FAIL (current code allows event_flag from READY participants, zone_history will have 2 entries)

- [ ] **Step 3: Implement the guards**

In `server/speedfog_racing/websocket/mod.py`, replace the status check in `handle_event_flag` (line 509-510):

```python
        # Old:
        if participant.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED):
            return  # Silently drop: player finished or abandoned

        # New:
        if participant.status != ParticipantStatus.PLAYING:
            return  # Only PLAYING participants can trigger events
```

In `handle_zone_query` (line 624-625), same replacement:

```python
        # Old:
        if participant.status in (ParticipantStatus.FINISHED, ParticipantStatus.ABANDONED):
            return  # Silently drop: player finished or abandoned

        # New:
        if participant.status != ParticipantStatus.PLAYING:
            return  # Only PLAYING participants can trigger zone queries
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && uv run pytest tests/test_integration.py::test_event_flag_ignored_when_participant_not_playing -v`
Expected: PASS

- [ ] **Step 5: Run full test suite to check for regressions**

Run: `cd server && uv run pytest tests/test_integration.py -v`
Expected: all tests pass

- [ ] **Step 6: Commit**

```bash
git add server/speedfog_racing/websocket/mod.py server/tests/test_integration.py
git commit -m "fix: tighten event_flag and zone_query guards to PLAYING status only"
```

## Task 4: Add IGT gate for training sessions

**Files:**

- Modify: `server/speedfog_racing/websocket/training_mod.py:320-346` (add IGT gate)
- Test: `server/tests/test_training.py` (add tests)

- [ ] **Step 1: Write failing test for training stale save rejection**

Add to `server/tests/test_training.py`:

```python
def test_training_stale_save_rejected(training_ws_client, training_session_data):
    """Training status_update with high IGT on first init should be rejected."""
    sid = training_session_data["session_id"]
    token = training_session_data["mod_token"]

    with training_ws_client.websocket_connect(f"/ws/training/{sid}") as ws:
        ws.send_json({"type": "auth", "mod_token": token})
        ws.receive_json()  # auth_ok
        ws.receive_json()  # race_start
        ws.receive_json()  # initial zone_update (start node)

        # Send status_update with stale IGT (60 seconds)
        ws.send_json({"type": "status_update", "igt_ms": 60_000, "death_count": 0})
        resp = ws.receive_json()
        assert resp["type"] == "error"
        assert "New Game" in resp["message"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd server && uv run pytest tests/test_training.py::test_training_stale_save_rejected -v`
Expected: FAIL (no gate yet, status_update proceeds normally)

- [ ] **Step 3: Implement IGT gate in training handler**

In `server/speedfog_racing/websocket/training_mod.py`, add the import:

```python
from speedfog_racing.websocket.common import (
    MAX_FRESH_IGT_MS,
    ...existing imports...
)
```

In `_handle_status_update`, insert the gate **before** the `igt_ms` write (before current line 335), after the status check (line 330-333). The training handler does not need log dedup since each session is a single connection (no repeated warnings from multiple participants).

```python
        # Gate: reject stale saves on first initialization
        igt_ms_val = msg.get("igt_ms")
        if (
            isinstance(igt_ms_val, int)
            and not session.zone_history
            and igt_ms_val > MAX_FRESH_IGT_MS
        ):
            logger.warning(
                "Rejected stale save: training=%s igt_ms=%d",
                session_id,
                igt_ms_val,
            )
            await send_error(websocket, "Please start a New Game")
            return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd server && uv run pytest tests/test_training.py::test_training_stale_save_rejected -v`
Expected: PASS

- [ ] **Step 5: Write and run self-healing test for training**

```python
def test_training_stale_save_self_heals(training_ws_client, training_session_data):
    """After stale rejection, a fresh save (low IGT) should succeed in training."""
    sid = training_session_data["session_id"]
    token = training_session_data["mod_token"]

    with training_ws_client.websocket_connect(f"/ws/training/{sid}") as ws:
        ws.send_json({"type": "auth", "mod_token": token})
        ws.receive_json()  # auth_ok
        ws.receive_json()  # race_start
        ws.receive_json()  # initial zone_update (start node)

        # Stale save rejected
        ws.send_json({"type": "status_update", "igt_ms": 60_000, "death_count": 0})
        resp = ws.receive_json()
        assert resp["type"] == "error"

        # Player starts New Game, IGT resets
        ws.send_json({"type": "status_update", "igt_ms": 500, "death_count": 0})
        resp = ws.receive_json()
        assert resp["type"] == "leaderboard_update"
        assert resp["participants"][0]["zone_history"] is not None
        assert len(resp["participants"][0]["zone_history"]) == 1
```

Run: `cd server && uv run pytest tests/test_training.py::test_training_stale_save_self_heals -v`
Expected: PASS

- [ ] **Step 6: Write and run resumption test (existing session not blocked)**

```python
def test_training_resumed_session_not_blocked(
    training_ws_client, training_session_data, async_session
):
    """A resumed training session (existing zone_history) should NOT be blocked by IGT gate."""
    import asyncio
    import uuid as _uuid

    sid = training_session_data["session_id"]
    token = training_session_data["mod_token"]

    # First connection: initialize zone_history normally
    with training_ws_client.websocket_connect(f"/ws/training/{sid}") as ws:
        ws.send_json({"type": "auth", "mod_token": token})
        ws.receive_json()  # auth_ok
        ws.receive_json()  # race_start
        ws.receive_json()  # initial zone_update

        ws.send_json({"type": "status_update", "igt_ms": 1000, "death_count": 0})
        ws.receive_json()  # leaderboard_update

    # Verify zone_history was initialized
    async def check_history():
        async with async_session() as db:
            result = await db.execute(
                select(TrainingSession).where(TrainingSession.id == _uuid.UUID(sid))
            )
            s = result.scalar_one()
            return s.zone_history

    history = asyncio.run(check_history())
    assert history is not None and len(history) >= 1

    # Reconnect with high IGT (simulating resume after long play)
    with training_ws_client.websocket_connect(f"/ws/training/{sid}") as ws:
        ws.send_json({"type": "auth", "mod_token": token})
        ws.receive_json()  # auth_ok
        ws.receive_json()  # race_start
        ws.receive_json()  # zone_update (reconnect sends last zone)

        # High IGT should be accepted (zone_history already exists)
        ws.send_json({"type": "status_update", "igt_ms": 120_000, "death_count": 0})
        resp = ws.receive_json()
        assert resp["type"] == "leaderboard_update"  # NOT error
```

Run: `cd server && uv run pytest tests/test_training.py::test_training_resumed_session_not_blocked -v`
Expected: PASS

- [ ] **Step 7: Run full training test suite**

Run: `cd server && uv run pytest tests/test_training.py -v`
Expected: all tests pass

- [ ] **Step 8: Commit**

```bash
git add server/speedfog_racing/websocket/training_mod.py server/tests/test_training.py
git commit -m "feat: add stale save IGT gate for training sessions"
```

## Task 5: Add set_status to mod Error handler

**Files:**

- Modify: `mod/src/dll/tracker.rs` (add `set_status` call in `IncomingMessage::Error` handler)

- [ ] **Step 1: Add set_status call to Error handler**

In `mod/src/dll/tracker.rs`, find the `IncomingMessage::Error` match arm and add `self.set_status(e)`:

```rust
            IncomingMessage::Error(e) => {
                self.last_received_debug = Some(format!("error({})", e));
                warn!(error = %e, "[WS] Error");
                self.set_status(e);
            }
```

- [ ] **Step 2: Verify it compiles**

Run: `cd mod && cargo check --lib`
Expected: compiles with no errors

- [ ] **Step 3: Run mod tests**

Run: `cd mod && cargo test`
Expected: all tests pass

- [ ] **Step 4: Commit**

```bash
git add mod/src/dll/tracker.rs
git commit -m "fix: display server error messages on mod overlay via set_status"
```

## Task 6: Run full test suites and lint

**Files:** none (verification only)

- [ ] **Step 1: Run full server test suite**

Run: `cd server && uv run pytest -v`
Expected: all tests pass

- [ ] **Step 2: Run linting**

Run: `cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy speedfog_racing/`
Expected: no errors

- [ ] **Step 3: Run mod check**

Run: `cd mod && cargo check --lib && cargo test`
Expected: compiles and tests pass
