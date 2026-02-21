# Per-Zone Death Tracking — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Track deaths per zone for each participant via server-side delta computation and display them in the MetroDAG node popup.

**Architecture:** The server computes death deltas from the cumulative `death_count` in periodic `status_update` messages. Deltas are attributed to the `zone_history` entry matching `participant.current_zone` and stored inline as a `deaths` field. The frontend reads this field and displays it in the node popup's "Visited by" section.

**Tech Stack:** Python/FastAPI (server), SvelteKit 5 (web), pytest + vitest (tests)

**Design doc:** `docs/plans/2026-02-21-per-zone-death-tracking.md`

---

## Task 1: Server — Per-zone death attribution in status_update handler

- Modify: `server/speedfog_racing/websocket/mod.py:335-338`

Step 1 — Write the implementation:

In `handle_status_update()`, replace the simple death_count assignment (lines 337-338) with delta computation and zone attribution. The new logic goes before updating `participant.death_count`:

```python
        if isinstance(msg.get("igt_ms"), int):
            participant.igt_ms = msg["igt_ms"]

        new_death_count = msg.get("death_count")
        if isinstance(new_death_count, int):
            delta = new_death_count - participant.death_count
            if delta > 0 and participant.current_zone and participant.zone_history:
                history = participant.zone_history
                for entry in history:
                    if entry.get("node_id") == participant.current_zone:
                        entry["deaths"] = entry.get("deaths", 0) + delta
                        break
                # Reassign to trigger SQLAlchemy JSON mutation detection
                participant.zone_history = list(history)
            participant.death_count = new_death_count
```

Key points:

- Delta computed as `new_death_count - participant.death_count` (both are cumulative)
- Find zone_history entry matching `current_zone` (not last entry — handles revisits correctly)
- `participant.zone_history = list(history)` creates a new list to trigger SQLAlchemy dirty detection on JSON columns
- `participant.death_count` is always updated (total counter still accurate)
- If `current_zone` is None or `zone_history` is empty, deaths are still tracked globally but not attributed to a zone

Step 2 — Run existing tests to verify no regression:

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/server && uv run pytest tests/test_websocket.py tests/test_integration.py -v --timeout=30`
Expected: All existing tests pass

Step 3 — Commit:

```bash
git add server/speedfog_racing/websocket/mod.py
git commit -m "feat(server): attribute deaths to current zone in zone_history"
```

---

## Task 2: Server — Integration test for per-zone death tracking

- Modify: `server/tests/test_integration.py`

Step 1 — Write the integration test:

Add after `test_zone_history_accumulates` (around line 812). This test verifies that `status_update` messages with increasing `death_count` attribute deaths to the correct zone_history entry:

```python
def test_per_zone_death_tracking(integration_client, race_with_participants, integration_db):
    """Deaths are attributed to the zone_history entry matching current_zone."""
    import asyncio

    race_id = race_with_participants["race_id"]
    organizer = race_with_participants["organizer"]
    players = race_with_participants["players"]

    # Start the race
    response = integration_client.post(
        f"/api/races/{race_id}/start",
        headers={"Authorization": f"Bearer {organizer.api_token}"},
    )
    assert response.status_code == 200

    with integration_client.websocket_connect(f"/ws/mod/{race_id}") as ws0:
        mod0 = ModTestClient(ws0, players[0]["mod_token"])
        assert mod0.auth()["type"] == "auth_ok"

        # Transition to PLAYING (sets start zone in zone_history)
        mod0.send_status_update(igt_ms=1000, death_count=0)
        mod0.receive()  # leaderboard_update

        # Die twice in start zone
        mod0.send_status_update(igt_ms=5000, death_count=2)
        mod0.receive()  # player_update

        # Discover node_a
        mod0.send_event_flag(9000000, igt_ms=10000)
        mod0.receive_until_type("leaderboard_update")

        # Die three times in node_a
        mod0.send_status_update(igt_ms=15000, death_count=5)
        mod0.receive()  # player_update

    # Verify zone_history deaths in DB
    async def check_deaths():
        async with integration_db() as db:
            result = await db.execute(
                select(Participant).where(
                    Participant.race_id == uuid.UUID(race_id),
                    Participant.user_id == players[0]["user"].id,
                )
            )
            p = result.scalar_one()
            return p.zone_history, p.death_count

    history, total_deaths = asyncio.run(check_deaths())
    assert total_deaths == 5
    assert len(history) == 2

    # start_node got 2 deaths
    start_entry = next(e for e in history if e["node_id"] == "start_node")
    assert start_entry["deaths"] == 2

    # node_a got 3 deaths
    node_a_entry = next(e for e in history if e["node_id"] == "node_a")
    assert node_a_entry["deaths"] == 3
```

Step 2 — Run the test:

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/server && uv run pytest tests/test_integration.py::test_per_zone_death_tracking -v --timeout=30`
Expected: PASS

Step 3 — Commit:

```bash
git add server/tests/test_integration.py
git commit -m "test(server): integration test for per-zone death tracking"
```

---

## Task 3: Frontend — Update TypeScript types and visitor computation

- Modify: `web/src/lib/websocket.ts:22`
- Modify: `web/src/lib/dag/popupData.ts:28-33,162-192`

Step 1 — Update WsParticipant zone_history type:

In `web/src/lib/websocket.ts`, line 22, change:

```typescript
zone_history: {
  node_id: string;
  igt_ms: number;
}
[] | null;
```

to:

```typescript
zone_history: { node_id: string; igt_ms: number; deaths?: number }[] | null;
```

Step 2 — Add deaths to PopupVisitor and computeVisitors:

In `web/src/lib/dag/popupData.ts`, add `deaths` to the `PopupVisitor` interface (line 28-33):

```typescript
export interface PopupVisitor {
  displayName: string;
  color: string;
  arrivedAtMs: number;
  timeSpentMs?: number;
  deaths?: number;
}
```

In `computeVisitors()` (line 182-188), add `deaths` when pushing to the visitors array:

```typescript
visitors.push({
  displayName: p.twitch_display_name || p.twitch_username,
  color: PLAYER_COLORS[p.color_index % PLAYER_COLORS.length],
  arrivedAtMs: entry.igt_ms,
  timeSpentMs: timeSpentMs != null && timeSpentMs > 0 ? timeSpentMs : undefined,
  deaths: entry.deaths && entry.deaths > 0 ? entry.deaths : undefined,
});
```

Step 3 — Run type check:

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check`
Expected: No type errors

Step 4 — Commit:

```bash
git add web/src/lib/websocket.ts web/src/lib/dag/popupData.ts
git commit -m "feat(web): add deaths field to zone_history type and PopupVisitor"
```

---

## Task 4: Frontend — Unit tests for deaths in computeVisitors

- Modify: `web/src/lib/dag/__tests__/popupData.test.ts`

Step 1 — Add test cases:

Add to the existing `describe("computeVisitors")` block (after the last test, around line 246):

```typescript
it("includes deaths from zone_history entries", () => {
  const withDeaths = [
    {
      ...participants[0],
      zone_history: [
        { node_id: "start", igt_ms: 0, deaths: 1 },
        { node_id: "stormveil", igt_ms: 60000, deaths: 5 },
        { node_id: "liurnia", igt_ms: 120000 },
        { node_id: "caelid", igt_ms: 200000, deaths: 3 },
      ],
    },
  ];
  const stormveil = computeVisitors("stormveil", withDeaths);
  expect(stormveil[0].deaths).toBe(5);

  const liurnia = computeVisitors("liurnia", withDeaths);
  expect(liurnia[0].deaths).toBeUndefined(); // no deaths = undefined

  const caelid = computeVisitors("caelid", withDeaths);
  expect(caelid[0].deaths).toBe(3);
});

it("returns undefined deaths when field is missing (backward compat)", () => {
  // Original zone_history format without deaths field
  const visitors = computeVisitors("stormveil", participants);
  expect(visitors[0].deaths).toBeUndefined();
});
```

Step 2 — Run the tests:

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npx vitest run src/lib/dag/__tests__/popupData.test.ts`
Expected: All tests pass

Step 3 — Commit:

```bash
git add web/src/lib/dag/__tests__/popupData.test.ts
git commit -m "test(web): unit tests for deaths in computeVisitors"
```

---

## Task 5: Frontend — Display deaths in NodePopup

- Modify: `web/src/lib/dag/NodePopup.svelte:148-165` (template)
- Modify: `web/src/lib/dag/NodePopup.svelte:313-342` (styles)

Step 1 — Update the Visited By template:

Replace lines 152-162 in `NodePopup.svelte`:

```svelte
  {#each data.visitors as visitor}
   <div class="visitor-item">
    <span class="player-dot" style="background: {visitor.color};"></span>
    <span class="visitor-name">{visitor.displayName}</span>
    <span class="visitor-times">
     {#if visitor.deaths}
      <span class="visitor-deaths">☠{visitor.deaths}</span>
     {/if}
     <span class="visitor-time">{formatIgt(visitor.arrivedAtMs)}</span>
     {#if visitor.timeSpentMs}
      <span class="visitor-duration">({formatIgt(visitor.timeSpentMs)})</span>
     {/if}
    </span>
   </div>
  {/each}
```

Step 2 — Add the deaths style:

Add after the `.visitor-duration` rule (around line 342):

```css
.visitor-deaths {
  color: #e05050;
  font-size: 0.75rem;
}
```

Step 3 — Verify visually:

Run: `cd /home/dev/src/games/ER/fog/speedfog-racing/web && npm run check`
Expected: No errors

Step 4 — Commit:

```bash
git add web/src/lib/dag/NodePopup.svelte
git commit -m "feat(web): display per-zone deaths in MetroDAG node popup"
```
