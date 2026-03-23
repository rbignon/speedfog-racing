# Race Detail UI Restructure + Chat Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Declutter the race detail sidebar by moving organizer controls under the DAG, add editable registration settings, and introduce a collapsible right sidebar with race chat and OBS overlay links.

**Architecture:** Three-column layout: left sidebar (live info only: leaderboard, casters, participants), main content (DAG + toolbar below it for organizer/participant actions), right sidebar (collapsible chat panel + OBS overlays). Chat uses the existing spectator WebSocket with new message types (ephemeral, no DB persistence).

**Tech Stack:** SvelteKit 5 (runes), FastAPI WebSocket, Pydantic v2, existing design system tokens

---

## File Structure

### New Files

| File                                            | Responsibility                                                    |
| ----------------------------------------------- | ----------------------------------------------------------------- |
| `web/src/lib/components/ChatSidebar.svelte`     | Collapsible right panel: OBS overlays (top), chat messages, input |
| `web/src/lib/components/ChatPanel.svelte`       | Chat message list with role/trait badges + input field            |
| `web/src/lib/components/DropdownMenu.svelte`    | Generic "..." dropdown menu (reusable)                            |
| `server/tests/test_update_race_registration.py` | Tests for max_participants/open_registration update               |
| `server/tests/test_chat_websocket.py`           | Tests for chat message handling                                   |

### Modified Files

| File                                            | Changes                                                                                  |
| ----------------------------------------------- | ---------------------------------------------------------------------------------------- |
| `server/speedfog_racing/schemas.py`             | Add `max_participants`, `open_registration` to `UpdateRaceRequest`                       |
| `server/speedfog_racing/api/races.py`           | Handle new update fields with validation                                                 |
| `server/speedfog_racing/websocket/schemas.py`   | Add `ChatBroadcastMessage` (with `role`, `dominant_trait`), `SendChatMessage`            |
| `server/speedfog_racing/websocket/spectator.py` | Handle incoming chat messages, role-gate sending, broadcast to room                      |
| `web/src/lib/api.ts`                            | Extend `updateRace` type signature                                                       |
| `web/src/lib/websocket.ts`                      | Add `ChatMessage` type, `onChatMessage` callback, public `send` method                   |
| `web/src/lib/stores/race.svelte.ts`             | Add `send()` method, `onChatMessage` callback, `chatMessages` state                      |
| `web/src/lib/components/RaceControls.svelte`    | Overwrite: becomes organizer toolbar (actions, public/private, registration, "..." menu) |
| `web/src/routes/race/[id]/+page.svelte`         | 3-column layout, move RaceControls under DAG, wire chat sidebar                          |

---

## Task 1: Server - Extend UpdateRaceRequest with registration settings

Allow organizers to update `max_participants` and `open_registration` during SETUP.

**Files:**

- Modify: `server/speedfog_racing/schemas.py:38-46`
- Modify: `server/speedfog_racing/api/races.py:423-496`
- Create: `server/tests/test_update_race_registration.py`

- [ ] **Step 1: Write failing tests for registration update**

In `server/tests/test_update_race_registration.py`.

The project uses a sync `TestClient` from conftest.py (not async). Create organizer + race inline following existing test patterns:

```python
"""Tests for updating race registration settings."""

import uuid

from speedfog_racing.models import Race, RaceStatus, Seed, User


def _create_organizer(db_session) -> tuple[User, str]:
    """Create an organizer user and return (user, api_token)."""
    token = f"test-token-{uuid.uuid4().hex[:8]}"
    user = User(
        twitch_id=f"twitch-{uuid.uuid4().hex[:8]}",
        twitch_username=f"organizer_{uuid.uuid4().hex[:6]}",
        api_token=token,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user, token


def _create_race(db_session, organizer: User, *, status=RaceStatus.SETUP) -> Race:
    """Create a race in the given status."""
    seed = Seed(total_layers=3, graph_json={"nodes": {}, "edges": []})
    db_session.add(seed)
    db_session.flush()
    race = Race(
        name=f"Test Race {uuid.uuid4().hex[:6]}",
        organizer_id=organizer.id,
        seed_id=seed.id,
        status=status,
    )
    db_session.add(race)
    db_session.commit()
    db_session.refresh(race)
    return race


def test_update_max_participants(client):
    """Organizer can update max_participants during SETUP."""
    from conftest import TestingSessionLocal

    db = TestingSessionLocal()
    organizer, token = _create_organizer(db)
    race = _create_race(db, organizer)
    db.close()

    response = client.patch(
        f"/api/races/{race.id}",
        json={"max_participants": 16},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["max_participants"] == 16


def test_update_open_registration(client):
    """Organizer can toggle open_registration during SETUP."""
    from conftest import TestingSessionLocal

    db = TestingSessionLocal()
    organizer, token = _create_organizer(db)
    race = _create_race(db, organizer)
    db.close()

    response = client.patch(
        f"/api/races/{race.id}",
        json={"open_registration": True, "max_participants": 8},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["open_registration"] is True
    assert response.json()["max_participants"] == 8


def test_update_registration_not_in_running(client):
    """Cannot update registration settings when race is running."""
    from conftest import TestingSessionLocal

    db = TestingSessionLocal()
    organizer, token = _create_organizer(db)
    race = _create_race(db, organizer, status=RaceStatus.RUNNING)
    db.close()

    response = client.patch(
        f"/api/races/{race.id}",
        json={"max_participants": 16},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400


def test_open_registration_requires_max_participants(client):
    """open_registration=True requires max_participants >= 2."""
    from conftest import TestingSessionLocal

    db = TestingSessionLocal()
    organizer, token = _create_organizer(db)
    race = _create_race(db, organizer)
    db.close()

    response = client.patch(
        f"/api/races/{race.id}",
        json={"open_registration": True},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 400
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd server && uv run pytest tests/test_update_race_registration.py -v`
Expected: FAIL (fields not handled yet, 422 or ignored)

- [ ] **Step 3: Update UpdateRaceRequest schema**

In `server/speedfog_racing/schemas.py`, replace the `UpdateRaceRequest` class:

```python
class UpdateRaceRequest(BaseModel):
    """Request to update race properties. Organizer only.

    scheduled_at: only editable in SETUP status.
    is_public: editable at any status.
    open_registration, max_participants: only editable in SETUP status.
    """

    scheduled_at: datetime | None = None
    is_public: bool | None = None
    open_registration: bool | None = None
    max_participants: int | None = None
```

- [ ] **Step 4: Handle new fields in update_race endpoint**

In `server/speedfog_racing/api/races.py`, in the `update_race` function, add handling after the `scheduled_at` block and before `await db.commit()`:

```python
    # open_registration / max_participants only editable in SETUP
    if request.open_registration is not None or "max_participants" in request.model_fields_set:
        if race.status != RaceStatus.SETUP:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Can only update registration settings for setup races",
            )

        if "max_participants" in request.model_fields_set:
            if request.max_participants is not None and request.max_participants > 100:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="max_participants cannot exceed 100",
                )
            race.max_participants = request.max_participants

        if request.open_registration is not None:
            race.open_registration = request.open_registration

        # Cross-field validation (same as CreateRaceRequest)
        if race.open_registration:
            if race.max_participants is None or race.max_participants < 2:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="max_participants must be >= 2 when open_registration is enabled",
                )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd server && uv run pytest tests/test_update_race_registration.py -v`
Expected: all PASS

- [ ] **Step 6: Run full test suite**

Run: `cd server && uv run pytest --timeout=30 -x -q`
Expected: all PASS

- [ ] **Step 7: Update frontend API types**

In `web/src/lib/api.ts`, update the `updateRace` function signature:

```typescript
export async function updateRace(
  raceId: string,
  data: {
    scheduled_at?: string | null;
    is_public?: boolean;
    open_registration?: boolean;
    max_participants?: number | null;
  },
): Promise<Race> {
```

- [ ] **Step 8: Commit**

```bash
git add server/speedfog_racing/schemas.py server/speedfog_racing/api/races.py \
  server/tests/test_update_race_registration.py web/src/lib/api.ts
git commit -m "feat: allow updating registration settings during SETUP"
```

---

## Task 2: Create DropdownMenu component

Generic "..." dropdown for reuse in the toolbar.

**Files:**

- Create: `web/src/lib/components/DropdownMenu.svelte`

- [ ] **Step 1: Create DropdownMenu component**

```svelte
<script lang="ts">
 interface MenuItem {
  label: string;
  danger?: boolean;
  disabled?: boolean;
  onclick: () => void;
 }

 interface Props {
  items: MenuItem[];
 }

 let { items }: Props = $props();
 let open = $state(false);

 function handleClick(item: MenuItem) {
  if (item.disabled) return;
  open = false;
  item.onclick();
 }

 function handleClickOutside(event: MouseEvent) {
  if (!(event.target as HTMLElement).closest('.dropdown-menu')) {
   open = false;
  }
 }
</script>

<svelte:window onclick={handleClickOutside} />

<div class="dropdown-menu">
 <button class="trigger" onclick={() => (open = !open)} title="More actions">
  <svg width="16" height="16" viewBox="0 0 16 16" fill="currentColor">
   <circle cx="8" cy="3" r="1.5" />
   <circle cx="8" cy="8" r="1.5" />
   <circle cx="8" cy="13" r="1.5" />
  </svg>
 </button>
 {#if open}
  <div class="menu">
   {#each items as item}
    <button
     class="menu-item"
     class:danger={item.danger}
     disabled={item.disabled}
     onclick={() => handleClick(item)}
    >
     {item.label}
    </button>
   {/each}
  </div>
 {/if}
</div>

<style>
 .dropdown-menu {
  position: relative;
 }

 .trigger {
  background: none;
  border: 1px solid var(--color-border);
  color: var(--color-text-secondary);
  border-radius: var(--radius-sm);
  padding: 0.4rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all var(--transition);
 }

 .trigger:hover {
  border-color: var(--color-text-secondary);
  color: var(--color-text);
 }

 .menu {
  position: absolute;
  right: 0;
  top: calc(100% + 4px);
  background: var(--color-surface-elevated);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  min-width: 160px;
  z-index: 50;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.3);
  padding: 0.25rem;
 }

 .menu-item {
  display: block;
  width: 100%;
  padding: 0.5rem 0.75rem;
  background: none;
  border: none;
  color: var(--color-text);
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
  text-align: left;
  cursor: pointer;
  border-radius: var(--radius-sm);
  transition: background var(--transition);
 }

 .menu-item:hover {
  background: rgba(255, 255, 255, 0.05);
 }

 .menu-item.danger {
  color: var(--color-danger);
 }

 .menu-item.danger:hover {
  background: rgba(239, 68, 68, 0.1);
 }

 .menu-item:disabled {
  opacity: 0.5;
  cursor: not-allowed;
 }
</style>
```

- [ ] **Step 2: Verify it renders**

Run: `cd web && npm run check`
Expected: no type errors

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/components/DropdownMenu.svelte
git commit -m "feat: add reusable DropdownMenu component"
```

---

## Task 3: Overwrite RaceControls as organizer toolbar

Replace the existing RaceControls component with a horizontal toolbar for organizer-only actions: state-dependent buttons, public/private toggle, registration settings, and "..." dropdown (Reset, Delete). Download and Rage quit stay in the left sidebar.

**Files:**

- Modify: `web/src/lib/components/RaceControls.svelte` (full overwrite)

- [ ] **Step 1: Overwrite RaceControls.svelte with toolbar content**

This component replaces the old vertical RaceControls with a horizontal toolbar. Organizer-only (Download + Rage quit remain in sidebar).

```svelte
<script lang="ts">
 import {
  releaseSeeds,
  rerollSeed,
  startRace,
  resetRace,
  finishRace,
  fetchRace,
  updateRace,
  type RaceDetail
 } from '$lib/api';
 import { auth } from '$lib/stores/auth.svelte';
 import ConfirmModal from './ConfirmModal.svelte';
 import DropdownMenu from './DropdownMenu.svelte';

 interface Props {
  race: RaceDetail;
  raceStatus: string;
  onRaceUpdated: (race: RaceDetail) => void;
  onDeleteRace: () => void;
 }

 let {
  race,
  raceStatus,
  onRaceUpdated,
  onDeleteRace
 }: Props = $props();

 let loading = $state(false);
 let error = $state<string | null>(null);
 let canStart = $derived(race.participants.length >= 2 || auth.isAdmin);

 // Registration editing
 let editingReg = $state(false);
 let regMaxPlayers = $state<number | null>(null);
 let regOpen = $state(false);
 let regSaving = $state(false);
 let regError = $state<string | null>(null);

 function startEditRegistration() {
  regMaxPlayers = race.max_participants;
  regOpen = race.open_registration;
  regError = null;
  editingReg = true;
 }

 async function saveRegistration() {
  regSaving = true;
  regError = null;
  try {
   await updateRace(race.id, {
    open_registration: regOpen,
    max_participants: regOpen ? regMaxPlayers : race.max_participants
   });
   const updated = await fetchRace(race.id);
   onRaceUpdated(updated);
   editingReg = false;
  } catch (e) {
   regError = e instanceof Error ? e.message : 'Failed to update';
  } finally {
   regSaving = false;
  }
 }

 // Confirm modal
 let pendingConfirm = $state<{
  title: string;
  message: string;
  confirmLabel: string;
  danger?: boolean;
  action: () => Promise<void>;
 } | null>(null);

 function requestConfirm(opts: NonNullable<typeof pendingConfirm>) {
  pendingConfirm = opts;
 }

 async function executeConfirm() {
  if (!pendingConfirm) return;
  const action = pendingConfirm.action;
  pendingConfirm = null;
  await action();
 }

 async function handleRelease() {
  loading = true;
  error = null;
  try {
   const updated = await releaseSeeds(race.id);
   onRaceUpdated(updated);
  } catch (e) {
   error = e instanceof Error ? e.message : 'Failed to release seeds';
  } finally {
   loading = false;
  }
 }

 function handleReroll() {
  requestConfirm({
   title: 'Re-roll Seed',
   message: seedsReleased
    ? 'Participants may have already downloaded. Re-rolling will require everyone to re-download. Continue?'
    : 'Re-roll the seed? Participants will need to download a new seed pack.',
   confirmLabel: 'Re-roll',
   async action() {
    loading = true;
    error = null;
    try {
     const updated = await rerollSeed(race.id);
     onRaceUpdated(updated);
    } catch (e) {
     error = e instanceof Error ? e.message : 'Failed to re-roll seed';
    } finally {
     loading = false;
    }
   }
  });
 }

 function handleStart() {
  requestConfirm({
   title: 'Start Race',
   message: 'Start the race? All participants will be notified.',
   confirmLabel: 'Start',
   async action() {
    loading = true;
    error = null;
    try {
     await startRace(race.id);
     const updated = await fetchRace(race.id);
     onRaceUpdated(updated);
    } catch (e) {
     error = e instanceof Error ? e.message : 'Failed to start race';
    } finally {
     loading = false;
    }
   }
  });
 }

 function handleForceFinish() {
  requestConfirm({
   title: 'Force Finish',
   message: 'Force finish this race? Non-finished participants will keep their current progress.',
   confirmLabel: 'Force Finish',
   async action() {
    loading = true;
    error = null;
    try {
     await finishRace(race.id);
     const updated = await fetchRace(race.id);
     onRaceUpdated(updated);
    } catch (e) {
     error = e instanceof Error ? e.message : 'Failed to finish race';
    } finally {
     loading = false;
    }
   }
  });
 }

 function handleReset() {
  requestConfirm({
   title: 'Reset Race',
   message: 'Reset this race? All participant progress will be cleared.',
   confirmLabel: 'Reset',
   danger: true,
   async action() {
    loading = true;
    error = null;
    try {
     await resetRace(race.id);
     const updated = await fetchRace(race.id);
     onRaceUpdated(updated);
    } catch (e) {
     error = e instanceof Error ? e.message : 'Failed to reset race';
    } finally {
     loading = false;
    }
   }
  });
 }

 async function handleToggleVisibility() {
  loading = true;
  try {
   await updateRace(race.id, { is_public: !race.is_public });
   const updated = await fetchRace(race.id);
   onRaceUpdated(updated);
  } catch (e) {
   error = e instanceof Error ? e.message : 'Failed to toggle visibility';
  } finally {
   loading = false;
  }
 }

 let dropdownItems = $derived.by(() => {
  const items: { label: string; danger?: boolean; disabled?: boolean; onclick: () => void }[] = [];
  if (raceStatus === 'running' || raceStatus === 'finished') {
   items.push({ label: 'Reset Race', danger: true, disabled: loading, onclick: handleReset });
  }
  items.push({
   label: 'Delete Race',
   danger: true,
   onclick: onDeleteRace
  });
  return items;
 });
</script>

<div class="toolbar">
 {#if error}
  <p class="toolbar-error">{error}</p>
 {/if}

 <div class="toolbar-row">
  <!-- Left: primary actions -->
  <div class="toolbar-actions">
   {#if raceStatus === 'setup'}
    {#if seedsReleased}
     <button class="btn btn-primary" onclick={handleStart} disabled={loading || !canStart}>
      {loading ? 'Starting...' : 'Start Race'}
     </button>
     {#if !canStart}
      <span class="hint">Need 2+ participants</span>
     {/if}
    {:else}
     <button class="btn btn-primary" onclick={handleRelease} disabled={loading}>
      {loading ? 'Releasing...' : 'Release Seeds'}
     </button>
    {/if}
    <button class="btn btn-secondary" onclick={handleReroll} disabled={loading}>
     Re-roll Seed
    </button>
    {#if seedsReleased}
     <span class="released-badge">Seeds released</span>
    {/if}
   {:else if raceStatus === 'running'}
    <button class="btn btn-primary" onclick={handleForceFinish} disabled={loading}>
     {loading ? 'Finishing...' : 'Force Finish'}
    </button>
   {/if}
  </div>

  <!-- Right: settings + overflow menu -->
  <div class="toolbar-settings">
   <button
    class="btn btn-ghost"
    onclick={handleToggleVisibility}
    disabled={loading}
    title={race.is_public ? 'Make private' : 'Make public'}
   >
     {#if race.is_public}
      <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14">
       <path d="M10 12a2 2 0 100-4 2 2 0 000 4z" />
       <path
        fill-rule="evenodd"
        d="M.458 10C1.732 5.943 5.522 3 10 3s8.268 2.943 9.542 7c-1.274 4.057-5.064 7-9.542 7S1.732 14.057.458 10zM14 10a4 4 0 11-8 0 4 4 0 018 0z"
        clip-rule="evenodd"
       />
      </svg>
      Public
     {:else}
      <svg viewBox="0 0 20 20" fill="currentColor" width="14" height="14">
       <path
        fill-rule="evenodd"
        d="M3.707 2.293a1 1 0 00-1.414 1.414l14 14a1 1 0 001.414-1.414l-1.473-1.473A10.014 10.014 0 0019.542 10C18.268 5.943 14.478 3 10 3a9.958 9.958 0 00-4.512 1.074l-1.78-1.781zm4.261 4.26l1.514 1.515a2.003 2.003 0 012.45 2.45l1.514 1.514a4 4 0 00-5.478-5.478z"
        clip-rule="evenodd"
       />
       <path
        d="M12.454 16.697L9.75 13.992a4 4 0 01-3.742-3.741L2.335 6.578A9.98 9.98 0 00.458 10c1.274 4.057 5.065 7 9.542 7 .847 0 1.669-.105 2.454-.303z"
       />
      </svg>
      Private
     {/if}
    </button>

    {#if raceStatus === 'setup'}
     {#if editingReg}
      <div class="reg-edit">
       <label class="reg-toggle">
        <input type="checkbox" bind:checked={regOpen} />
        Open registration
       </label>
       {#if regOpen}
        <label class="reg-field">
         Max:
         <input
          type="number"
          min="2"
          max="100"
          bind:value={regMaxPlayers}
          class="reg-input"
         />
        </label>
       {/if}
       <button class="btn btn-sm btn-primary" onclick={saveRegistration} disabled={regSaving}>
        {regSaving ? '...' : 'Save'}
       </button>
       <button class="btn btn-sm btn-ghost" onclick={() => (editingReg = false)}>
        Cancel
       </button>
       {#if regError}
        <span class="reg-error">{regError}</span>
       {/if}
      </div>
     {:else}
      <button class="btn btn-ghost" onclick={startEditRegistration} title="Registration settings">
       {#if race.open_registration}
        Open ({race.max_participants} max)
       {:else}
        Invite only
       {/if}
      </button>
     {/if}
    {/if}
   {#if dropdownItems.length > 0}
    <DropdownMenu items={dropdownItems} />
   {/if}
  </div>
 </div>
</div>

{#if pendingConfirm}
 <ConfirmModal
  title={pendingConfirm.title}
  message={pendingConfirm.message}
  confirmLabel={pendingConfirm.confirmLabel}
  danger={pendingConfirm.danger ?? false}
  onConfirm={executeConfirm}
  onCancel={() => (pendingConfirm = null)}
 />
{/if}

<style>
 .toolbar {
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: var(--color-surface);
  padding: 0.5rem 0.75rem;
 }

 .toolbar-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 0.5rem;
  flex-wrap: wrap;
 }

 .toolbar-actions {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
 }

 .toolbar-settings {
  display: flex;
  align-items: center;
  gap: 0.5rem;
 }

 .toolbar-error {
  color: var(--color-danger);
  font-size: var(--font-size-sm);
  margin: 0 0 0.5rem 0;
 }

 .btn {
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
  padding: 0.4rem 0.75rem;
  border-radius: var(--radius-sm);
  cursor: pointer;
  display: inline-flex;
  align-items: center;
  gap: 0.35rem;
  transition: all var(--transition);
  white-space: nowrap;
 }

 .btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
 }

 .btn-primary {
  background: var(--color-gold);
  color: var(--color-bg);
  border: none;
  font-weight: 600;
 }

 .btn-primary:hover:not(:disabled) {
  background: var(--color-gold-hover);
 }

 .btn-secondary {
  background: transparent;
  border: 1px solid var(--color-border);
  color: var(--color-text);
 }

 .btn-secondary:hover:not(:disabled) {
  border-color: var(--color-text-secondary);
 }

 .btn-ghost {
  background: none;
  border: none;
  color: var(--color-text-secondary);
  padding: 0.4rem 0.5rem;
 }

 .btn-ghost:hover:not(:disabled) {
  color: var(--color-text);
 }

 .btn-danger-outline {
  background: transparent;
  border: 1px solid var(--color-danger);
  color: var(--color-danger);
 }

 .btn-danger-outline:hover:not(:disabled) {
  background: rgba(239, 68, 68, 0.1);
 }

 .btn-sm {
  padding: 0.25rem 0.5rem;
  font-size: var(--font-size-xs);
 }

 .hint {
  font-size: var(--font-size-xs);
  color: var(--color-text-disabled);
 }

 .released-badge {
  font-size: var(--font-size-xs);
  color: var(--color-success, #10b981);
  font-weight: 500;
 }

 .reg-edit {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  flex-wrap: wrap;
 }

 .reg-toggle {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 0.3rem;
  cursor: pointer;
 }

 .reg-field {
  font-size: var(--font-size-sm);
  color: var(--color-text-secondary);
  display: flex;
  align-items: center;
  gap: 0.3rem;
 }

 .reg-input {
  width: 4rem;
  padding: 0.2rem 0.4rem;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
 }

 .reg-error {
  color: var(--color-danger);
  font-size: var(--font-size-xs);
 }

 /* SVGs in buttons */
 .btn :global(svg) {
  flex-shrink: 0;
 }
</style>
```

- [ ] **Step 2: Verify it compiles**

Run: `cd web && npm run check`
Expected: no type errors

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/components/RaceControls.svelte
git commit -m "feat: overwrite RaceControls as horizontal organizer toolbar"
```

---

## Task 4: Restructure race detail page - move controls to toolbar

Move organizer controls and visibility out of the sidebar. RaceControls (now a toolbar) renders under the DAG. Download and Rage quit stay in the sidebar.

**Files:**

- Modify: `web/src/routes/race/[id]/+page.svelte`

- [ ] **Step 1: Move RaceControls under the DAG**

`RaceControls` import already exists. Move its usage from the sidebar to the main content area, after the DAG wrapper div and before stats/highlights. Render for organizers only:

```svelte
{#if isOrganizer}
 <RaceControls
  race={initialRace}
  {raceStatus}
  onRaceUpdated={handleRaceUpdated}
  onDeleteRace={() => (showDeleteConfirm = true)}
 />
{/if}
```

- [ ] **Step 2: Remove organizer-only controls from sidebar**

Remove from the sidebar for each status:

**RUNNING state:** Remove `<RaceControls>`. Keep Download button and Rage quit in sidebar.

**SETUP state:** Remove `<RaceControls>` and OBS overlay button (OBS moves to chat sidebar). Keep Download button in sidebar.

**FINISHED state:** Remove `<RaceControls>`.

The visibility-row at line ~646 (shared across all states, after the if/else block) should also be removed since Public/Private + Delete are now in the toolbar.

- [ ] **Step 3: Verify compilation**

Run: `cd web && npm run check`
Expected: no type errors

- [ ] **Step 4: Commit**

```bash
git add "web/src/routes/race/[id]/+page.svelte"
git commit -m "feat: move organizer controls to toolbar under DAG"
```

---

## Task 5: Server - Add chat WebSocket message handling

Add chat message support to the spectator WebSocket. Chat is ephemeral (broadcast only, no persistence).

**Files:**

- Modify: `server/speedfog_racing/websocket/schemas.py`
- Modify: `server/speedfog_racing/websocket/spectator.py`
- Create: `server/tests/test_chat_websocket.py`
- Note: `manager.py` unchanged; uses existing `RaceRoom.broadcast_to_all()`

- [ ] **Step 1: Add chat message schemas**

In `server/speedfog_racing/websocket/schemas.py`, add:

```python
# --- Client -> Server Messages (Chat) ---

class SendChatMessage(BaseModel):
    """Chat message from authenticated spectator/caster."""

    type: Literal["chat"] = "chat"
    message: str = Field(max_length=500)


# --- Server -> Client Messages (Chat) ---

class ChatBroadcastMessage(BaseModel):
    """Chat message broadcast to room."""

    type: Literal["chat_message"] = "chat_message"
    username: str
    display_name: str | None
    avatar_url: str | None
    role: str  # "organizer" | "caster" | "participant"
    dominant_trait: str | None  # e.g. "rusher", "explorer", null
    message: str
    timestamp: str
```

- [ ] **Step 2: Verify broadcast_to_all exists on RaceRoom**

The existing `RaceRoom.broadcast_to_all(message)` method already broadcasts to both mods and spectators via `asyncio.gather`. No new method needed; chat will use it directly.

- [ ] **Step 3: Handle chat messages in spectator handler**

In `server/speedfog_racing/websocket/spectator.py`, replace the passive receive loop with active message handling:

```python
async def handle_spectator_websocket(
    websocket: WebSocket, race_id: uuid.UUID, session_maker: async_sessionmaker[AsyncSession]
) -> None:
    """Handle a spectator WebSocket connection with optional auth."""
    await websocket.accept()

    query_locale = websocket.query_params.get("locale", "en")
    conn = SpectatorConnection(websocket=websocket, locale=query_locale)

    try:
        async with session_maker() as db:
            race = await get_race_with_details(db, race_id)
            if not race:
                await websocket.close(code=4004, reason="Race not found")
                return

            user_id = await _try_auth(websocket, db)
            conn.user_id = user_id

            # Load user info + role for chat if authenticated
            chat_info: dict[str, str | None] | None = None
            if user_id:
                from speedfog_racing.models import PlayerTraitScores, User

                user_result = await db.execute(select(User).where(User.id == user_id))
                user_obj = user_result.scalar_one_or_none()
                if user_obj:
                    if user_obj.locale:
                        conn.locale = user_obj.locale

                    # Determine role in this race
                    role: str | None = None
                    if race.organizer_id == user_id:
                        role = "organizer"
                    elif any(c.user_id == user_id for c in race.casters):
                        role = "caster"
                    elif any(p.user_id == user_id for p in race.participants):
                        role = "participant"

                    # Load dominant trait
                    trait_result = await db.execute(
                        select(PlayerTraitScores.dominant_trait).where(
                            PlayerTraitScores.user_id == user_id
                        )
                    )
                    dominant_trait = trait_result.scalar_one_or_none()

                    if role:  # Only allow chat for actors
                        chat_info = {
                            "username": user_obj.twitch_username,
                            "display_name": user_obj.twitch_display_name,
                            "avatar_url": user_obj.twitch_avatar_url,
                            "role": role,
                            "dominant_trait": dominant_trait,
                        }

            await send_race_state(websocket, race, locale=conn.locale)

        await manager.connect_spectator(race_id, conn)
        heartbeat_task = asyncio.create_task(heartbeat_loop(websocket))

        try:
            while True:
                try:
                    raw = await websocket.receive_text()
                    # Handle chat messages from authenticated users
                    if chat_info:
                        await _handle_spectator_message(
                            raw, race_id, chat_info
                        )
                except WebSocketDisconnect:
                    break
        finally:
            heartbeat_task.cancel()
            try:
                await heartbeat_task
            except asyncio.CancelledError:
                pass

    except WebSocketDisconnect:
        logger.info(f"Spectator disconnected: race={race_id}")
    except Exception as e:
        logger.error(f"Error in spectator websocket: {e}")
    finally:
        await manager.disconnect_spectator(race_id, conn)


async def _handle_spectator_message(
    raw: str,
    race_id: uuid.UUID,
    chat_info: dict[str, str | None],
) -> None:
    """Process an incoming message from an authorized chat user (participant/organizer/caster)."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return

    msg_type = data.get("type")
    if msg_type == "pong":
        return  # heartbeat response, ignore

    if msg_type == "chat":
        message_text = data.get("message", "").strip()
        if not message_text or len(message_text) > 500:
            return

        from speedfog_racing.websocket.schemas import ChatBroadcastMessage

        broadcast = ChatBroadcastMessage(
            username=chat_info["username"] or "",
            display_name=chat_info.get("display_name"),
            avatar_url=chat_info.get("avatar_url"),
            role=chat_info["role"] or "participant",
            dominant_trait=chat_info.get("dominant_trait"),
            message=message_text,
            timestamp=datetime.now(UTC).isoformat(),
        )
        room = manager.get_room(race_id)
        if room:
            await room.broadcast_to_all(broadcast.model_dump_json())
```

- [ ] **Step 4: Write tests for chat**

In `server/tests/test_chat_websocket.py`:

```python
"""Tests for chat WebSocket messages."""

import pytest


@pytest.mark.asyncio
async def test_chat_message_schema():
    """ChatBroadcastMessage serializes correctly."""
    from speedfog_racing.websocket.schemas import ChatBroadcastMessage

    msg = ChatBroadcastMessage(
        username="testuser",
        display_name="TestUser",
        avatar_url=None,
        message="Hello race!",
        timestamp="2026-03-23T12:00:00+00:00",
    )
    data = msg.model_dump()
    assert data["type"] == "chat_message"
    assert data["username"] == "testuser"
    assert data["message"] == "Hello race!"


@pytest.mark.asyncio
async def test_send_chat_message_schema():
    """SendChatMessage validates correctly."""
    from speedfog_racing.websocket.schemas import SendChatMessage

    msg = SendChatMessage(message="Hello!")
    assert msg.type == "chat"
    assert msg.message == "Hello!"


@pytest.mark.asyncio
async def test_send_chat_message_max_length():
    """SendChatMessage rejects messages over 500 chars."""
    from pydantic import ValidationError

    from speedfog_racing.websocket.schemas import SendChatMessage

    with pytest.raises(ValidationError):
        SendChatMessage(message="x" * 501)
```

- [ ] **Step 5: Run tests**

Run: `cd server && uv run pytest tests/test_chat_websocket.py -v`
Expected: all PASS

- [ ] **Step 6: Run full test suite**

Run: `cd server && uv run pytest --timeout=30 -x -q`
Expected: all PASS

- [ ] **Step 7: Commit**

```bash
git add server/speedfog_racing/websocket/schemas.py \
  server/speedfog_racing/websocket/spectator.py \
  server/tests/test_chat_websocket.py
git commit -m "feat: add ephemeral chat via spectator WebSocket"
```

---

## Task 6: Frontend - Extend WebSocket client for chat

Add chat message type and send capability to the existing WS client.

**Files:**

- Modify: `web/src/lib/websocket.ts`

- [ ] **Step 1: Add ChatMessage type and callback**

In `web/src/lib/websocket.ts`, add after `SpectatorCountMessage`:

```typescript
export interface ChatMessage {
  type: "chat_message";
  username: string;
  display_name: string | null;
  avatar_url: string | null;
  role: string; // "organizer" | "caster" | "participant"
  dominant_trait: string | null;
  message: string;
  timestamp: string;
}
```

Update `ServerMessage` union:

```typescript
export type ServerMessage =
  | RaceStateMessage
  | LeaderboardUpdateMessage
  | PlayerUpdateMessage
  | RaceStatusChangeMessage
  | SpectatorCountMessage
  | ChatMessage;
```

Add `"chat_message"` to `VALID_SERVER_MESSAGE_TYPES` set.

Add callback to `RaceWebSocketOptions`:

```typescript
onChatMessage?: (msg: ChatMessage) => void;
```

- [ ] **Step 2: Add send method and chat handler**

Add a public `send` method to `RaceWebSocket`:

```typescript
send(data: Record<string, unknown>): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
        this.ws.send(JSON.stringify(data));
    }
}
```

Add case to `handleMessage`:

```typescript
case "chat_message":
    this.options.onChatMessage?.(msg);
    break;
```

- [ ] **Step 3: Verify compilation**

Run: `cd web && npm run check`
Expected: no type errors

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/websocket.ts
git commit -m "feat: add chat message support to WebSocket client"
```

---

## Task 7: Frontend - Extend RaceStore with chat support

Add `send()`, `onChatMessage` callback, and `chatMessages` state to the race store so the page can send/receive chat messages through the existing WebSocket.

**Files:**

- Modify: `web/src/lib/stores/race.svelte.ts`

- [ ] **Step 1: Add chat state and send method to RaceStore**

In `web/src/lib/stores/race.svelte.ts`:

Add import for `ChatMessage`:

```typescript
import {
  createRaceWebSocket,
  type RaceWebSocket,
  type ChatMessage,
  type WsParticipant,
  type WsRaceInfo,
  type WsSeedInfo,
} from "$lib/websocket";
```

Add state and method to `RaceStore` class:

```typescript
chatMessages = $state<ChatMessage[]>([]);

// Inside connect(), add the onChatMessage callback to createRaceWebSocket options:
onChatMessage: (msg) => {
    this.chatMessages = [...this.chatMessages, msg];
},

// Add public send method:
send(data: Record<string, unknown>): void {
    this.ws?.send(data);
}
```

In the `disconnect()` method, also clear chat:

```typescript
this.chatMessages = [];
```

In the `connect()` method initialization (where `this.participants = []` etc.), also reset chat:

```typescript
this.chatMessages = [];
```

- [ ] **Step 2: Verify compilation**

Run: `cd web && npm run check`
Expected: no type errors

- [ ] **Step 3: Commit**

```bash
git add web/src/lib/stores/race.svelte.ts
git commit -m "feat: add chat support to RaceStore (send + messages)"
```

---

## Task 8: Frontend - Create ChatPanel and ChatSidebar components

Build the chat UI and collapsible right sidebar.

**Files:**

- Create: `web/src/lib/components/ChatPanel.svelte`
- Create: `web/src/lib/components/ChatSidebar.svelte`

- [ ] **Step 1: Create ChatPanel component**

`web/src/lib/components/ChatPanel.svelte`:

```svelte
<script lang="ts">
 import type { ChatMessage } from '$lib/websocket';

 interface Props {
  messages: ChatMessage[];
  canSend: boolean;
  onSend: (message: string) => void;
 }

 let { messages, canSend, onSend }: Props = $props();

 const TRAIT_META: Record<string, { icon: string; color: string }> = {
  rusher: { icon: '\u26A1', color: '#EF4444' },
  cautious: { icon: '\uD83D\uDEE1\uFE0F', color: '#10B981' },
  boss_slayer: { icon: '\u2694\uFE0F', color: '#FBBF24' },
  resilient: { icon: '\uD83D\uDCAA', color: '#C8A44E' },
  explorer: { icon: '\uD83C\uDF10', color: '#3B82F6' },
  pathfinder: { icon: '\uD83E\uDDED', color: '#A78BFA' },
  rage_quitter: { icon: '\uD83D\uDCA5', color: '#DC2626' }
 };

 let input = $state('');
 let messagesEl: HTMLDivElement | undefined = $state();

 $effect(() => {
  // Scroll to bottom when new messages arrive
  if (messages.length && messagesEl) {
   messagesEl.scrollTop = messagesEl.scrollHeight;
  }
 });

 function handleSubmit(e: Event) {
  e.preventDefault();
  const text = input.trim();
  if (!text) return;
  onSend(text);
  input = '';
 }

 function handleKeydown(e: KeyboardEvent) {
  if (e.key === 'Enter' && !e.shiftKey) {
   e.preventDefault();
   handleSubmit(e);
  }
 }

 function formatTime(timestamp: string): string {
  const d = new Date(timestamp);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
 }
</script>

<div class="chat-panel">
 <div class="messages" bind:this={messagesEl}>
  {#if messages.length === 0}
   <p class="empty">No messages yet</p>
  {:else}
   {#each messages as msg}
    <div class="message">
     <div class="msg-header">
      {#if msg.avatar_url}
       <img src={msg.avatar_url} alt="" class="msg-avatar" />
      {/if}
      {#if msg.role === 'organizer'}
       <span class="badge badge-organizer" title="Organizer">ORG</span>
      {:else if msg.role === 'caster'}
       <span class="badge badge-caster" title="Caster">CAST</span>
      {/if}
      {#if msg.dominant_trait && TRAIT_META[msg.dominant_trait]}
       {@const trait = TRAIT_META[msg.dominant_trait]}
       <span class="badge" style="background: {trait.color}20; color: {trait.color}" title={msg.dominant_trait}>
        {trait.icon}
       </span>
      {/if}
      <span class="msg-name">{msg.display_name || msg.username}</span>
      <span class="msg-time">{formatTime(msg.timestamp)}</span>
     </div>
     <p class="msg-text">{msg.message}</p>
    </div>
   {/each}
  {/if}
 </div>

 {#if canSend}
  <form class="chat-input" onsubmit={handleSubmit}>
   <input
    type="text"
    placeholder="Send a message..."
    bind:value={input}
    onkeydown={handleKeydown}
    maxlength="500"
   />
   <button type="submit" disabled={!input.trim()}>
    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
     <path d="M22 2L11 13M22 2l-7 20-4-9-9-4 20-7z" />
    </svg>
   </button>
  </form>
 {/if}
</div>

<style>
 .chat-panel {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
 }

 .messages {
  flex: 1;
  overflow-y: auto;
  padding: 0.5rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
 }

 .empty {
  color: var(--color-text-disabled);
  font-size: var(--font-size-sm);
  text-align: center;
  margin-top: 2rem;
 }

 .message {
  font-size: var(--font-size-sm);
 }

 .msg-header {
  display: flex;
  align-items: center;
  gap: 0.3rem;
  margin-bottom: 0.1rem;
 }

 .msg-avatar {
  width: 18px;
  height: 18px;
  border-radius: 50%;
  flex-shrink: 0;
 }

 .badge {
  font-size: 0.6rem;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 0.05rem 0.3rem;
  border-radius: 3px;
  flex-shrink: 0;
  line-height: 1.4;
 }

 .badge-organizer {
  background: rgba(200, 164, 78, 0.2);
  color: var(--color-gold);
 }

 .badge-caster {
  background: rgba(239, 68, 68, 0.15);
  color: #f87171;
 }

 .msg-name {
  font-weight: 600;
  color: var(--color-text);
  font-size: var(--font-size-xs);
 }

 .msg-time {
  color: var(--color-text-disabled);
  font-size: var(--font-size-xs);
  margin-left: auto;
 }

 .msg-text {
  margin: 0;
  color: var(--color-text-secondary);
  word-break: break-word;
  line-height: 1.4;
 }

 .chat-input {
  display: flex;
  gap: 0.5rem;
  padding: 0.5rem;
  border-top: 1px solid var(--color-border);
 }

 .chat-input input {
  flex: 1;
  padding: 0.4rem 0.6rem;
  background: var(--color-bg);
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  color: var(--color-text);
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
 }

 .chat-input input:focus {
  outline: none;
  border-color: var(--color-purple);
 }

 .chat-input button {
  background: var(--color-purple);
  border: none;
  border-radius: var(--radius-sm);
  color: white;
  padding: 0.4rem 0.6rem;
  cursor: pointer;
  display: flex;
  align-items: center;
  transition: background var(--transition);
 }

 .chat-input button:hover:not(:disabled) {
  background: var(--color-purple-hover);
 }

 .chat-input button:disabled {
  opacity: 0.5;
  cursor: not-allowed;
 }

</style>
```

- [ ] **Step 2: Create ChatSidebar component**

`web/src/lib/components/ChatSidebar.svelte`:

```svelte
<script lang="ts">
 import type { ChatMessage } from '$lib/websocket';
 import ChatPanel from './ChatPanel.svelte';

 interface Props {
  messages: ChatMessage[];
  canSend: boolean;
  collapsed: boolean;
  showObsButton: boolean;
  onSend: (message: string) => void;
  onToggle: () => void;
  onOpenObs: () => void;
 }

 let {
  messages,
  canSend,
  collapsed,
  showObsButton,
  onSend,
  onToggle,
  onOpenObs
 }: Props = $props();

 let unreadCount = $state(0);
 let lastSeenCount = $state(0);

 $effect(() => {
  if (collapsed && messages.length > lastSeenCount) {
   unreadCount = messages.length - lastSeenCount;
  }
  if (!collapsed) {
   unreadCount = 0;
   lastSeenCount = messages.length;
  }
 });
</script>

<aside class="chat-sidebar" class:collapsed>
 <button class="toggle-btn" onclick={onToggle} title={collapsed ? 'Open chat' : 'Close chat'}>
  {#if collapsed}
   <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M21 15a2 2 0 01-2 2H7l-4 4V5a2 2 0 012-2h14a2 2 0 012 2z" />
   </svg>
   {#if unreadCount > 0}
    <span class="unread-badge">{unreadCount}</span>
   {/if}
  {:else}
   <svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
    <path d="M18 6L6 18M6 6l12 12" />
   </svg>
  {/if}
 </button>

 {#if !collapsed}
  <div class="sidebar-content">
   {#if showObsButton}
    <button class="obs-btn" onclick={onOpenObs}>
     OBS Overlays
    </button>
   {/if}

   <div class="sidebar-header">
    <h3>Chat</h3>
   </div>

   <div class="chat-area">
    <ChatPanel {messages} {canSend} {onSend} />
   </div>
  </div>
 {/if}
</aside>

<style>
 .chat-sidebar {
  width: 320px;
  background: var(--color-surface);
  border-left: 1px solid var(--color-border);
  display: flex;
  flex-direction: column;
  position: relative;
  transition: width 0.2s ease;
 }

 .chat-sidebar.collapsed {
  width: 44px;
 }

 .toggle-btn {
  position: absolute;
  top: 0.75rem;
  left: 50%;
  transform: translateX(-50%);
  background: none;
  border: none;
  color: var(--color-text-secondary);
  cursor: pointer;
  padding: 0.4rem;
  display: flex;
  align-items: center;
  justify-content: center;
  border-radius: var(--radius-sm);
  transition: color var(--transition);
  z-index: 1;
 }

 .collapsed .toggle-btn {
  position: static;
  transform: none;
  margin: 0.75rem auto 0;
 }

 .toggle-btn:hover {
  color: var(--color-text);
 }

 .unread-badge {
  position: absolute;
  top: -2px;
  right: -2px;
  background: var(--color-danger);
  color: white;
  font-size: 0.6rem;
  font-weight: 700;
  min-width: 16px;
  height: 16px;
  border-radius: 8px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0 3px;
 }

 .sidebar-content {
  display: flex;
  flex-direction: column;
  height: 100%;
  min-height: 0;
  padding-top: 2.5rem;
 }

 .sidebar-header {
  padding: 0 0.75rem 0.5rem;
  border-bottom: 1px solid var(--color-border);
 }

 .sidebar-header h3 {
  margin: 0;
  font-size: var(--font-size-sm);
  font-weight: 600;
  color: var(--color-text-secondary);
  text-transform: uppercase;
  letter-spacing: 0.05em;
 }

 .chat-area {
  flex: 1;
  min-height: 0;
 }

 .obs-btn {
  margin: 0.5rem 0.5rem 0;
  padding: 0.5rem;
  border: 1px solid var(--color-border);
  border-radius: var(--radius-sm);
  background: none;
  color: var(--color-text-secondary);
  font-family: var(--font-family);
  font-size: var(--font-size-sm);
  cursor: pointer;
  transition: all var(--transition);
 }

 .obs-btn:hover {
  border-color: var(--color-purple);
  color: var(--color-purple);
 }

 @media (max-width: 768px) {
  .chat-sidebar {
   display: none;
  }
 }
</style>
```

- [ ] **Step 3: Verify compilation**

Run: `cd web && npm run check`
Expected: no type errors

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/components/ChatPanel.svelte \
  web/src/lib/components/ChatSidebar.svelte
git commit -m "feat: add ChatPanel and ChatSidebar components"
```

---

## Task 9: Wire chat sidebar into race detail page

Integrate the 3-column layout, chat WebSocket, and OBS overlays into the race detail page.

**Files:**

- Modify: `web/src/routes/race/[id]/+page.svelte`

- [ ] **Step 1: Add chat imports and state**

Add import:

```typescript
import ChatSidebar from "$lib/components/ChatSidebar.svelte";
```

Add state variable (chat messages come from `raceStore.chatMessages`, no local state needed):

```typescript
let chatCollapsed = $state(true);
```

- [ ] **Step 2: Wire chat send function**

Chat messages are received automatically via `raceStore.chatMessages` (set up in Task 7).
Add a send function that delegates to the store:

```typescript
function sendChatMessage(message: string) {
  raceStore.send({ type: "chat", message });
}
```

- [ ] **Step 3: Update page layout to 3 columns**

Wrap the existing structure. The current layout is:

```html
<div class="race-page">
  <aside class="sidebar">...</aside>
  <main class="main-content">...</main>
</div>
```

Add ChatSidebar after main:

```svelte
<div class="race-page">
    <aside class="sidebar">...</aside>
    <main class="main-content">...</main>
    <ChatSidebar
        messages={raceStore.chatMessages}
        canSend={isOrganizer || isCaster || !!myParticipant}
        collapsed={chatCollapsed}
        showObsButton={isOrganizer || isCaster || !!myParticipant}
        onSend={sendChatMessage}
        onToggle={() => (chatCollapsed = !chatCollapsed)}
        onOpenObs={() => (showObsModal = true)}
    />
</div>
```

- [ ] **Step 4: Remove OBS overlay button from sidebar**

In the SETUP section of the sidebar, remove:

```svelte
{#if isOrganizer || isCaster || myParticipant}
    <button class="obs-overlay-btn" onclick={() => (showObsModal = true)}> OBS Overlays </button>
{/if}
```

This is now in the ChatSidebar.

- [ ] **Step 5: Verify compilation**

Run: `cd web && npm run check`
Expected: no type errors

- [ ] **Step 6: Test manually**

Run: `cd web && npm run dev`
Verify:

- Left sidebar shows only leaderboard (running) or participants (setup)
- Toolbar appears under DAG with appropriate buttons
- Right chat sidebar toggles open/closed
- Chat icon shows unread badge when collapsed
- OBS Overlays button is in the chat sidebar
- Public/Private toggle works in toolbar
- Registration editing works in SETUP toolbar

- [ ] **Step 7: Commit**

```bash
git add "web/src/routes/race/[id]/+page.svelte"
git commit -m "feat: integrate chat sidebar and 3-column layout"
```

---

## Task 10: Polish and cleanup

Final adjustments and removal of dead code.

**Files:**

- Modify: `web/src/routes/race/[id]/+page.svelte`

- [ ] **Step 1: Check for unused imports and dead CSS**

Search for any remaining unused imports or components in the race detail page.

- [ ] **Step 2: Remove dead CSS from race detail page**

Remove CSS rules that are no longer used:

- `.abandon-section`, `.abandon-btn`, `.abandon-error` (if rage quit moved to toolbar)
- `.sidebar-download-btn` (if download moved to toolbar)
- `.visibility-row`, `.btn-toggle-visibility`, `.btn-delete` (if moved to toolbar)
- `.obs-overlay-btn`

- [ ] **Step 3: Run type check and lint**

Run: `cd web && npm run check && npm run lint`
Expected: no errors

- [ ] **Step 4: Run full server tests**

Run: `cd server && uv run pytest --timeout=30 -x -q`
Expected: all PASS

- [ ] **Step 5: Commit**

Stage only the specific files that were cleaned up:

```bash
git add "web/src/routes/race/[id]/+page.svelte"
git commit -m "chore: remove dead code from sidebar restructure"
```

- [ ] **Step 6: Launch code review agent**

Use the code-reviewer agent to review all changes across this plan.
