<!-- markdownlint-disable MD001 MD036 -->

# User Overlay Settings — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Let users configure overlay font_size (and future settings) per-account, applied when generating seed packs.

**Architecture:** Add a `overlay_settings` JSON column on the `User` model. A new `PATCH /users/me/settings` endpoint validates and merges partial settings. `generate_player_config()` and `generate_training_config()` read the user's settings to inject into the TOML. The Settings page gets an Overlay section.

**Tech Stack:** Python/FastAPI, SQLAlchemy 2.0 (async), Alembic, Pydantic v2, SvelteKit 5, Rust (mod config default only)

---

### Task 1: DB Model + Alembic Migration

**Files:**

- Modify: `server/speedfog_racing/models.py:63-79` (User class)
- Create: `server/alembic/versions/xxxx_add_overlay_settings_to_users.py` (via autogenerate)

**Step 1: Add `overlay_settings` column to User model**

In `server/speedfog_racing/models.py`, add the import and column:

The `JSON` import already exists at line 10. Add the column after `locale` (line 77):

```python
overlay_settings: Mapped[dict | None] = mapped_column(JSON, nullable=True)
```

**Step 2: Generate Alembic migration**

Run:

```bash
cd server && uv run alembic revision --autogenerate -m "add overlay_settings to users"
```

Expected: A new migration file in `server/alembic/versions/` with `op.add_column("users", sa.Column("overlay_settings", sa.JSON(), nullable=True))`.

**Step 3: Run migration on test DB**

Run:

```bash
cd server && uv run alembic upgrade head
```

Expected: No errors.

**Step 4: Commit**

```bash
git add server/speedfog_racing/models.py server/alembic/versions/*overlay_settings*
git commit -m "feat(server): add overlay_settings JSON column to User model"
```

---

### Task 2: Pydantic Schema + API Endpoint

**Files:**

- Modify: `server/speedfog_racing/api/users.py:85-101` (add new endpoint after `update_locale`)
- Modify: `server/speedfog_racing/api/auth.py:50-61` (add `overlay_settings` to `UserPublicResponse`)
- Modify: `server/speedfog_racing/api/users.py:65-74` (add `overlay_settings` to `MyProfileResponse`)

**Step 1: Write the failing test**

Create test in `server/tests/test_overlay_settings.py`:

```python
"""Tests for user overlay settings API."""

import os

os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test.db"
os.environ["SECRET_KEY"] = "test-secret-key"

import uuid

import pytest
from sqlalchemy import select

from speedfog_racing.models import User, generate_token


@pytest.fixture
def user_with_token(client):
    """Create a user in the DB and return (user, token)."""
    from tests.conftest import TestingSessionLocal

    db = TestingSessionLocal()
    token = generate_token()
    user = User(
        id=uuid.uuid4(),
        twitch_id=f"twitch_{uuid.uuid4().hex[:8]}",
        twitch_username="settingsuser",
        twitch_display_name="Settings User",
        api_token=token,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    db.close()
    return user, token


def test_update_overlay_settings(client, user_with_token):
    """PATCH /users/me/settings updates overlay_settings."""
    user, token = user_with_token
    response = client.patch(
        "/api/users/me/settings",
        json={"font_size": 24.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    data = response.json()
    assert data["overlay_settings"]["font_size"] == 24.0


def test_update_overlay_settings_validates_range(client, user_with_token):
    """PATCH /users/me/settings rejects out-of-range font_size."""
    _, token = user_with_token
    response = client.patch(
        "/api/users/me/settings",
        json={"font_size": 200.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 422


def test_update_overlay_settings_merges(client, user_with_token):
    """PATCH /users/me/settings merges with existing settings."""
    _, token = user_with_token
    # First set font_size
    client.patch(
        "/api/users/me/settings",
        json={"font_size": 20.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    # Then update again — should still have font_size
    response = client.patch(
        "/api/users/me/settings",
        json={"font_size": 22.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["overlay_settings"]["font_size"] == 22.0


def test_get_me_includes_overlay_settings(client, user_with_token):
    """/auth/me includes overlay_settings."""
    _, token = user_with_token
    client.patch(
        "/api/users/me/settings",
        json={"font_size": 24.0},
        headers={"Authorization": f"Bearer {token}"},
    )
    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["overlay_settings"] == {"font_size": 24.0}


def test_get_me_overlay_settings_null_by_default(client, user_with_token):
    """/auth/me returns null overlay_settings for new users."""
    # Create a fresh user with no settings
    from tests.conftest import TestingSessionLocal

    db = TestingSessionLocal()
    token = generate_token()
    user = User(
        id=uuid.uuid4(),
        twitch_id=f"twitch_{uuid.uuid4().hex[:8]}",
        twitch_username="freshuser",
        twitch_display_name="Fresh User",
        api_token=token,
    )
    db.add(user)
    db.commit()
    db.close()

    response = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 200
    assert response.json()["overlay_settings"] is None
```

**Step 2: Run tests to verify they fail**

Run:

```bash
cd server && uv run pytest tests/test_overlay_settings.py -v
```

Expected: FAIL (endpoint doesn't exist yet, overlay_settings not in response).

**Step 3: Add `OverlaySettingsRequest` schema and endpoint**

In `server/speedfog_racing/api/users.py`, after the `UpdateLocaleRequest` class (line 86), add:

```python
from pydantic import field_validator

class OverlaySettingsRequest(BaseModel):
    """Request to update overlay settings. Only provided fields are updated."""

    font_size: float | None = None

    @field_validator("font_size")
    @classmethod
    def validate_font_size(cls, v: float | None) -> float | None:
        if v is not None and not (8.0 <= v <= 72.0):
            raise ValueError("font_size must be between 8 and 72")
        return v
```

After the `update_locale` endpoint (line 101), add:

```python
@router.patch("/me/settings")
async def update_overlay_settings(
    body: OverlaySettingsRequest,
    user: Annotated[User, Depends(get_current_user)],
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Update overlay settings (merge with existing)."""
    current = user.overlay_settings or {}
    updates = body.model_dump(exclude_none=True)
    current.update(updates)
    user.overlay_settings = current
    await db.commit()
    return {"overlay_settings": user.overlay_settings}
```

**Step 4: Add `overlay_settings` to response schemas**

In `server/speedfog_racing/api/auth.py`, add to `UserPublicResponse` (line 58):

```python
overlay_settings: dict | None = None
```

In `server/speedfog_racing/api/users.py`, add to `MyProfileResponse` (line 72):

```python
overlay_settings: dict | None = None
```

**Step 5: Run tests to verify they pass**

Run:

```bash
cd server && uv run pytest tests/test_overlay_settings.py -v
```

Expected: All PASS.

**Step 6: Run full test suite**

Run:

```bash
cd server && uv run pytest -x
```

Expected: All PASS.

**Step 7: Commit**

```bash
git add server/speedfog_racing/api/users.py server/speedfog_racing/api/auth.py server/tests/test_overlay_settings.py
git commit -m "feat(server): add PATCH /users/me/settings for overlay configuration"
```

---

### Task 3: Seed Pack Generation — Use User Settings

**Files:**

- Modify: `server/speedfog_racing/services/seed_pack_service.py:22-67` (`generate_player_config`)
- Modify: `server/speedfog_racing/services/seed_pack_service.py:140-162` (`generate_training_config`)
- Modify: `server/tests/test_seed_pack_service.py` (update tests)

**Step 1: Write the failing test**

In `server/tests/test_seed_pack_service.py`, add after the existing `MockUser` class:

```python
def test_generate_player_config_uses_user_font_size(mock_participant, mock_race):
    """Config should use user's font_size when set."""
    mock_participant.user.overlay_settings = {"font_size": 24.0}
    config = generate_player_config(mock_participant, mock_race)
    assert "font_size = 24.0" in config


def test_generate_player_config_uses_default_font_size(mock_participant, mock_race):
    """Config should use 18.0 default when user has no settings."""
    mock_participant.user.overlay_settings = None
    config = generate_player_config(mock_participant, mock_race)
    assert "font_size = 18.0" in config
```

Also add `overlay_settings: dict | None = None` to the `MockUser` dataclass.

**Step 2: Run tests to verify they fail**

Run:

```bash
cd server && uv run pytest tests/test_seed_pack_service.py::test_generate_player_config_uses_user_font_size tests/test_seed_pack_service.py::test_generate_player_config_uses_default_font_size -v
```

Expected: FAIL (font_size is still hardcoded 32.0).

**Step 3: Implement overlay settings in config generation**

In `server/speedfog_racing/services/seed_pack_service.py`, add at the top (after imports):

```python
OVERLAY_DEFAULTS: dict[str, float] = {"font_size": 18.0}


def _get_overlay_setting(user_settings: dict | None, key: str) -> float:
    """Get overlay setting from user prefs or defaults."""
    if user_settings and key in user_settings:
        return user_settings[key]
    return OVERLAY_DEFAULTS[key]
```

Update `generate_player_config()` — change the signature to accept user settings and replace the hardcoded `font_size = 32.0`:

```python
def generate_player_config(
    participant: Participant,
    race: Race,
    websocket_url: str | None = None,
) -> str:
```

Inside the f-string, replace `font_size = 32.0` with:

```python
font_size = {_get_overlay_setting(participant.user.overlay_settings, "font_size")}
```

Do the same for `generate_training_config()` — the function takes a `TrainingSession` which has `session.user`. Replace `font_size = 32.0` with:

```python
font_size = {_get_overlay_setting(session.user.overlay_settings, "font_size")}
```

**Step 4: Run tests to verify they pass**

Run:

```bash
cd server && uv run pytest tests/test_seed_pack_service.py -v
```

Expected: All PASS.

**Step 5: Run full test suite**

Run:

```bash
cd server && uv run pytest -x
```

Expected: All PASS.

**Step 6: Commit**

```bash
git add server/speedfog_racing/services/seed_pack_service.py server/tests/test_seed_pack_service.py
git commit -m "feat(server): use user overlay_settings in seed pack config generation

Default font_size changed from 32.0 to 18.0."
```

---

### Task 4: Web — API Client + Settings Page

**Files:**

- Modify: `web/src/lib/api.ts:18-21` (add `overlay_settings` to `AuthUser`)
- Modify: `web/src/lib/api.ts` (add `updateOverlaySettings` function)
- Modify: `web/src/routes/settings/+page.svelte` (add Overlay section)

**Step 1: Add `overlay_settings` to the `AuthUser` type**

In `web/src/lib/api.ts`, update the `AuthUser` interface:

```typescript
export interface AuthUser extends User {
  role: string;
  locale: string | null;
  overlay_settings: { font_size?: number } | null;
}
```

**Step 2: Add `updateOverlaySettings` API function**

After the `updateLocale` function (around line 629), add:

```typescript
/**
 * Update the current user's overlay settings.
 */
export async function updateOverlaySettings(settings: {
  font_size?: number;
}): Promise<{ overlay_settings: { font_size?: number } }> {
  const response = await fetch(`${API_BASE}/users/me/settings`, {
    method: "PATCH",
    headers: {
      ...getAuthHeaders(),
      "Content-Type": "application/json",
    },
    body: JSON.stringify(settings),
  });
  return handleResponse<{ overlay_settings: { font_size?: number } }>(response);
}
```

**Step 3: Reorganize the Settings page with Overlay section**

Rewrite `web/src/routes/settings/+page.svelte` to add:

- An Overlay section with a number input for font_size (min 8, max 72, step 1, default 18)
- A single Save button at the bottom that saves both locale and overlay settings
- Keep the existing Language section

```svelte
<script lang="ts">
 import { onMount } from 'svelte';
 import { goto } from '$app/navigation';
 import { auth } from '$lib/stores/auth.svelte';
 import {
  fetchLocales,
  updateLocale,
  updateOverlaySettings,
  type LocaleInfo
 } from '$lib/api';

 let locales = $state<LocaleInfo[]>([]);
 let selectedLocale = $state('en');
 let fontSize = $state(18);
 let saving = $state(false);
 let error = $state<string | null>(null);
 let success = $state(false);

 onMount(async () => {
  if (!auth.isLoggedIn) {
   goto('/');
   return;
  }
  locales = await fetchLocales();
  selectedLocale = auth.user?.locale ?? 'en';
  fontSize = auth.user?.overlay_settings?.font_size ?? 18;
 });

 async function handleSave() {
  saving = true;
  error = null;
  success = false;
  try {
   const [localeResult, overlayResult] = await Promise.all([
    updateLocale(selectedLocale),
    updateOverlaySettings({ font_size: fontSize })
   ]);
   if (auth.user) {
    auth.user.locale = localeResult.locale;
    auth.user.overlay_settings = overlayResult.overlay_settings;
   }
   success = true;
   setTimeout(() => (success = false), 3000);
  } catch (e) {
   error = e instanceof Error ? e.message : 'Failed to save';
  } finally {
   saving = false;
  }
 }
</script>

<svelte:head>
 <title>Settings – SpeedFog Racing</title>
</svelte:head>

<main class="settings">
 <h1>Settings</h1>

 <section class="setting-group">
  <h2>Language</h2>
  <p class="description">
   Choose the language for zone names and fog gate descriptions during races.
  </p>

  <div class="locale-select">
   {#each locales as locale}
    <label>
     <input
      type="radio"
      name="locale"
      value={locale.code}
      checked={selectedLocale === locale.code}
      onchange={() => (selectedLocale = locale.code)}
     />
     {locale.name}
     {#if locale.code !== 'en'}
      <span class="locale-code">({locale.code})</span>
     {/if}
    </label>
   {/each}
  </div>
 </section>

 <section class="setting-group">
  <h2>Overlay</h2>
  <p class="description">
   Customize the in-game overlay that displays race information.
  </p>

  <div class="setting-row">
   <label for="font-size">Font size</label>
   <div class="input-with-unit">
    <input
     id="font-size"
     type="number"
     min="8"
     max="72"
     step="1"
     bind:value={fontSize}
    />
    <span class="unit">px</span>
   </div>
   <span class="hint">8–72 px (default: 18)</span>
  </div>
 </section>

 <div class="actions">
  <button class="btn btn-primary" onclick={handleSave} disabled={saving}>
   {saving ? 'Saving...' : 'Save'}
  </button>
  {#if success}
   <span class="success-msg">Saved!</span>
  {/if}
  {#if error}
   <span class="error-msg">{error}</span>
  {/if}
 </div>
</main>
```

Add styles for the new elements (`.setting-row`, `.input-with-unit`, `.unit`, `.hint`) and move `.actions` outside the section.

**Step 4: Run type check**

Run:

```bash
cd web && npm run check
```

Expected: No type errors.

**Step 5: Commit**

```bash
git add web/src/lib/api.ts web/src/routes/settings/+page.svelte
git commit -m "feat(web): add overlay font_size setting to Settings page"
```

---

### Task 5: Mod Default Update

**Files:**

- Modify: `mod/src/dll/config.rs:98-100` (change default_font_size)

**Step 1: Update the Rust default**

In `mod/src/dll/config.rs`, change `default_font_size()`:

```rust
fn default_font_size() -> f32 {
    18.0
}
```

**Step 2: Run cargo check**

Run:

```bash
cd mod && cargo check --lib
```

Expected: No errors.

**Step 3: Commit**

```bash
git add mod/src/dll/config.rs
git commit -m "feat(mod): change default overlay font_size from 32 to 18"
```

---

### Task 6: Final Verification

**Step 1: Run full server test suite**

Run:

```bash
cd server && uv run pytest -x -v
```

Expected: All PASS.

**Step 2: Run web type check and lint**

Run:

```bash
cd web && npm run check && npm run lint
```

Expected: No errors.

**Step 3: Run ruff and mypy**

Run:

```bash
cd server && uv run ruff check . && uv run ruff format --check . && uv run mypy speedfog_racing/
```

Expected: No errors.
