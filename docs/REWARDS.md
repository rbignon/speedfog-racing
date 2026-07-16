# Rewards System

Source-agnostic cosmetic recognition for SpeedFog Racing players. Two reward types:

- **Badges**: small icons displayed next to a player's name in leaderboards, chat, and profile cards.
- **Name templates**: visual customization of the player's name (color or gradient) and, in selected containers, of the surrounding row or card background.

Rewards are decoupled from any specific source: a badge can be granted by an admin, attributed automatically by an in-process detector (race winner, weekly daily champion), or filled in by a backfill script. Rewards are purely cosmetic, never tradable, and never affect gameplay or matchmaking.

The original design rationale lives in [`docs/specs/2026-04-30-rewards-system-design.md`](specs/2026-04-30-rewards-system-design.md). This document is the operational reference: what the system does today, how it is wired, and what the visual artifacts should look like.

---

## Functional Overview

### Catalog

The catalog is static Python configuration in [`server/speedfog_racing/rewards/catalog.py`](../server/speedfog_racing/rewards/catalog.py). Adding a reward is a code change followed by a deploy. There is no admin UI for catalog editing, on purpose: the catalog is small enough that drift between code and DB would cost more than it saves.

#### Badges

| id                      | name           | lifecycle | source                                                                                                                                                                                                     |
| ----------------------- | -------------- | --------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `early_adopter`         | Early Adopter  | permanent | Backfill: accounts created before `2026-04-01`.                                                                                                                                                            |
| `veteran`               | Veteran        | permanent | Auto: granted to users with at least `VETERAN_RACE_THRESHOLD` (currently `25`) finished race participations across all races. Checked after each race finish; the threshold lives in `rewards/catalog.py`. |
| `contributor`           | Contributor    | permanent | Admin grant only.                                                                                                                                                                                          |
| `weekly_daily_champion` | Daily Champion | transient | Auto: highest total weekly points over the previous Mon-Sun week (see Daily Seed `Weekly Points`).                                                                                                         |
| `weekly_daily_winner`   | Daily Winner   | transient | Auto: ranked 1st on at least one daily seed of the previous Mon-Sun week (ties included). Broader, lower tier than the points champion. Synced in the same Monday rollup.                                  |
| `frog`                  | Frog           | permanent | Auto: granted on a user's first FINISHED race participation (daily seeds count, solo training sessions do not). Checked after each race finish, same hook as `veteran`. The playful "Speedfrog" mascot.    |

Lifecycle:

- **Permanent**: granted once, kept forever (admin can revoke as a mistake-correction escape hatch).
- **Transient**: holder set is recomputed from an external condition; revoked when the player no longer meets it.

Ties are allowed: when the qualifying condition selects multiple players (e.g. several users tied for the most weekly daily-seed points), all of them hold the badge simultaneously.

#### Name templates

| id            | description                         | unlock                                                                         |
| ------------- | ----------------------------------- | ------------------------------------------------------------------------------ |
| `default`     | Solid white name                    | Always unlocked, never revocable                                               |
| `archon`      | Violet mono gradient (admin marker) | Granted to platform administrators                                             |
| `daily_crown` | Gold gradient + warm gold backdrop  | Granted permanently the first time a player tops the weekly daily-seed ranking |
| `dawnrunner`  | Cyan gradient                       | Granted permanently the first time a player wins a daily seed                  |
| `pioneer`     | Serif italic on parchment backdrop  | Granted to accounts created before the rewards system launched                 |
| `weathered`   | Bronze gradient (veteran tenure)    | Granted alongside the `veteran` badge, same threshold                          |
| `speedfrog`   | Green gradient (Speedfrog mascot)   | Granted on the player's first finished race (Speedfog -> frog)                 |

Name templates are **always permanent**. Once unlocked, they remain unlocked even if the player no longer meets the original condition (the gold-on-the-name memento outlasts the dynamic badge).

#### Phantom skins

| id             | name         | unlock                                                                                                                         | obtainable                        |
| -------------- | ------------ | ------------------------------------------------------------------------------------------------------------------------------ | --------------------------------- |
| `none`         | None         | Always unlocked, never revocable.                                                                                              | yes                               |
| `gold-aura`    | Gold Aura    | Granted permanently the first time a player tops the weekly daily-seed points ranking.                                         | yes                               |
| `silver-aura`  | Silver Aura  | Granted permanently the first time a player wins a public non-daily race with at least 2 racing participants.                  | yes                               |
| `cyan-aura`    | Cyan Aura    | Granted permanently the first time a player wins a daily seed (ties included).                                                 | yes                               |
| `molten-aura`  | Molten Aura  | Granted permanently the first time a player's best daily streak reaches `DAILY_STREAK_REWARD_THRESHOLD` (currently `14`) days. | yes                               |
| `emerald-aura` | Emerald Aura | Granted to accounts created before the rewards system launched.                                                                | **no** (cutoff `2026-04-01` past) |
| `crimson-aura` | Crimson Aura | Granted alongside the `veteran` badge, same threshold.                                                                         | yes                               |
| `violet-aura`  | Violet Aura  | Admin grant only (special events, organized tournaments).                                                                      | yes                               |

The `obtainable` column drives the picker UI: locked skins flagged `obtainable: false` are hidden from users who don't own them (the unlock condition has lapsed for good and surfacing it would just frustrate). Already-unlocked skins stay visible regardless of the flag.

Phantom skins are **always permanent**: once unlocked, they stay unlocked. The mod overlay receives the equipped skin's id via `auth_ok.phantom_skin` and resolves it to a SpEffect through `graph.json` per the speedfog integration spec. The skin is applied to the local player only; the cosmetic does not propagate to other participants on the web.

### Equip rules

- A player has at most **one badge equipped**. Slot can be empty.
- A player has exactly **one name template active**. Defaults to `default` (solid white) if nothing is set, or if the equipped one is revoked.
- A player has at most **one phantom skin equipped**. Slot can be empty (resolves to `none` and the mod applies no SpEffect).
- When a transient badge is revoked from a player who had it equipped, the equip slot is auto-cleared. The corresponding souvenir name template (`daily_crown` / `dawnrunner`) stays unlocked.

### Notifications

Each grant, revoke, or unlock writes a row in `reward_notifications`. The dashboard banner (`RewardsBanner.svelte`) reads pending notifications, summarizes them, and points the user to `/settings#rewards`. Click-through (or explicit dismiss) clears all pending notifications for that user.

Admin revokes do **not** emit notifications: they are mistake corrections, not events.

---

## Data Model

Four tables, plus three scalar columns on `users`.

### `users` (added columns)

| column                      | type              | notes                                                                            |
| --------------------------- | ----------------- | -------------------------------------------------------------------------------- |
| `equipped_badge_id`         | `String(50) NULL` | Logical key into the `BADGES` catalog                                            |
| `equipped_name_template_id` | `String(50) NULL` | Logical key into `NAME_TEMPLATES`. `NULL` resolves to `"default"`.               |
| `equipped_phantom_skin_id`  | `String(50) NULL` | Logical key into `PHANTOM_SKINS`. `NULL` resolves to `"none"` for the picker UI. |

### `badge_grants`

| column       | type                        | notes                         |
| ------------ | --------------------------- | ----------------------------- |
| `id`         | UUID PK                     |                               |
| `user_id`    | UUID FK `users.id`, indexed |                               |
| `badge_id`   | `String(50)`                | Logical key into `BADGES`     |
| `granted_at` | `DateTime(tz=True)`         | Default `now()`               |
| `revoked_at` | `DateTime(tz=True) NULL`    | `NULL` means currently held   |
| `granted_by` | UUID FK `users.id`, NULL    | `NULL` for auto/system grants |
| `reason`     | `String(200) NULL`          | Free-form audit trail         |

Index: `(badge_id, user_id) WHERE revoked_at IS NULL` for fast holder lookup during transient sync.

### `name_template_unlocks`

| column        | type                | notes |
| ------------- | ------------------- | ----- |
| `id`          | UUID PK             |       |
| `user_id`     | UUID FK, indexed    |       |
| `template_id` | `String(50)`        |       |
| `unlocked_at` | `DateTime(tz=True)` |       |
| `granted_by`  | UUID FK NULL        |       |
| `reason`      | `String(200) NULL`  |       |

Constraint: `UNIQUE (user_id, template_id)`.

### `phantom_skin_unlocks`

| column        | type                | notes |
| ------------- | ------------------- | ----- |
| `id`          | UUID PK             |       |
| `user_id`     | UUID FK, indexed    |       |
| `skin_id`     | `String(50)`        |       |
| `unlocked_at` | `DateTime(tz=True)` |       |
| `granted_by`  | UUID FK NULL        |       |
| `reason`      | `String(200) NULL`  |       |

Constraint: `UNIQUE (user_id, skin_id)`.

### `reward_notifications`

| column         | type                                                                                      | notes                |
| -------------- | ----------------------------------------------------------------------------------------- | -------------------- |
| `id`           | UUID PK                                                                                   |                      |
| `user_id`      | UUID FK, indexed                                                                          |                      |
| `kind`         | Enum(`badge_granted`, `badge_revoked`, `name_template_unlocked`, `phantom_skin_unlocked`) |                      |
| `reward_id`    | `String(50)`                                                                              |                      |
| `created_at`   | `DateTime(tz=True)`                                                                       |                      |
| `dismissed_at` | `DateTime(tz=True) NULL`                                                                  | `NULL` means pending |

---

## Server Architecture

```
server/speedfog_racing/
  rewards/
    __init__.py
    catalog.py          # BADGES, NAME_TEMPLATES, PHANTOM_SKINS dicts (frozen dataclasses)
    models_data.py      # Badge, NameTemplate dataclasses (config types, not ORM)
    service.py          # RewardsService
  models.py             # +BadgeGrant, +NameTemplateUnlock, +RewardNotification
  api/rewards.py        # Player endpoints (under /api/rewards)
  api/admin.py          # Admin grant/revoke endpoints
  scripts/backfill_rewards.py  # Idempotent CLI (run once after migration)
```

### Service API

`RewardsService` (in `service.py`) exposes:

- `grant_permanent_badge(user_id, badge_id, granted_by=None, reason=None)`: idempotent. Raises `LifecycleMismatchError` on transient ids, `UnknownRewardError` on unknown ones. Emits `badge_granted` notification only on actual creation.
- `grant_name_template(user_id, template_id, granted_by=None, reason=None)`: idempotent. `default` is always unlocked and is silently skipped. Emits `name_template_unlocked` only on actual creation.
- `sync_transient_holders(badge_id, new_holder_ids: set[UUID], reason=None) -> SyncResult`: atomic diff against current holders. Auto-clears `equipped_badge_id` on revoked users. Emits `badge_granted` / `badge_revoked` notifications.
- `grant_race_win_rewards(race)`: grants the permanent `silver-aura` phantom skin to the winner(s) of a finished public non-daily race with at least 2 racing participants (`igt_ms > 0`). Winner = FINISHED participant(s) with the lowest `igt_ms`. Idempotent through the first-time-only grant; requires `race.participants` eagerly loaded.
- `grant_daily_win_rewards(day: date, reason=None)`: grants the permanent `cyan-aura` phantom skin and `dawnrunner` name template to the winner(s) of the given day's closed daily (top `daily_points_for_race` score, ties included). No-op when the day has no FINISHED daily.
- `refresh_weekly_daily_rewards(week_starting: date, reason=None)`: over `[week_starting, week_starting + 7d)`, syncs `weekly_daily_champion` to the top total-points scorer(s) (and grants them `gold-aura` + `daily_crown`), and syncs `weekly_daily_winner` to everyone who ranked 1st on at least one daily that week.
- `check_finish_reward_milestones(user_id)`: counts the user's `Participant` rows with `status=FINISHED` and grants finished-race milestone rewards idempotently. At the first finish it grants `frog` (badge) and `speedfrog` (name template); at `VETERAN_RACE_THRESHOLD` (defined in `rewards/catalog.py`) it additionally grants `veteran` (badge), `weathered` (name template), and `crimson-aura` (phantom skin).
- `set_equipped_badge(user_id, badge_id: str | None)`: validates ownership, updates `users.equipped_badge_id`. Raises `NotOwnedError` if the user does not currently hold the badge.
- `set_equipped_name_template(user_id, template_id: str | None)`: validates ownership (`default` is always allowed), updates `users.equipped_name_template_id`.
- `check_daily_streak_eligibility(user_id)`: reads `users.daily_best_streak` and grants the permanent `molten-aura` phantom skin once it is at least `DAILY_STREAK_REWARD_THRESHOLD` (defined in `rewards/catalog.py`). Idempotent.
- `grant_phantom_skin(user_id, skin_id, granted_by=None, reason=None)`: idempotent. `none` is silently skipped (always unlocked). Emits `phantom_skin_unlocked` only on actual creation.
- `set_equipped_phantom_skin(user_id, skin_id: str | None)`: validates ownership (`none` and `None` both clear the column to NULL).
- `revoke_phantom_skin(user_id, skin_id)`: admin escape hatch. Auto-clears matching equip slot. Does not emit notifications.
- `get_user_inventory(user_id) -> Inventory`: held badges + unlocked templates + equip state, sorted by `sort_order`.
- `get_pending_notifications(user_id)`, `dismiss_notifications(user_id)`: banner read/clear.
- `revoke_badge(user_id, badge_id)`, `revoke_name_template(user_id, template_id)`: admin escape hatches. Auto-clear matching equip slots. Do **not** emit notifications.

### Integration points

- **Race win** (`services/race_lifecycle.py`, both finalization paths: `check_race_auto_finish` and `finalize_race`): once the race transitions to FINISHED, `grant_race_win_rewards(race)` grants the permanent `silver-aura` phantom skin to the winner(s) of a finished public non-daily race with at least 2 racing participants (`igt_ms > 0`).
- **Daily win** (`services/daily_seed_loop.py`): at each 08:00 UTC creation tick, after the recent dailies have been hard-closed, `grant_daily_win_rewards` is called once per day in the `DAILY_WIN_REWARD_LOOKBACK_DAYS` (7-day) window, granting the permanent `cyan-aura` phantom skin and `dawnrunner` name template to the winner(s) of each closed daily, ties included. Sweeping a window rather than just yesterday self-heals days where creation failed and the grant never ran; the grants are first-time-only, so already-rewarded dailies are no-ops.
- **Weekly champion** (`services/daily_seed_loop.py`, unchanged Monday rollup): when generating a daily seed for a Monday, call `refresh_weekly_daily_rewards(week_starting=monday-7d)`. It syncs two transient badges over the prior week's closed dailies: `weekly_daily_champion` to the user(s) with the maximum `total_points` (ties allowed; also granted `gold-aura` + `daily_crown`), and `weekly_daily_winner` to everyone who ranked 1st on at least one daily (the day-winner set, `compute_weekly_daily_winners`). Past weeks before the rollout are not backfilled.
- **Finished-race milestones** (`services/race_lifecycle.py`): in the same hook (after `grant_race_win_rewards`), iterate every participant who just transitioned to FINISHED and call `check_finish_reward_milestones(user_id)`. The service counts `Participant` rows with `status=FINISHED` for that user across all races (daily seeds included, solo training sessions excluded since they create no `Participant` row). The first finish grants the `frog` badge + `speedfrog` template; once the count reaches `VETERAN_RACE_THRESHOLD` the `veteran` badge + `weathered` template + `crimson-aura` skin are granted. All grants are idempotent, so calling on every race finish is safe.
- **Daily streak souvenir** (`websocket/race/mod.py`): inside `_apply_daily_streak`, after `apply_qualification_to_user` persists a streak increment, call `RewardsService.check_daily_streak_eligibility(user_id)`. The service reads `users.daily_best_streak` (so the same predicate covers live grants and backfill) and grants `molten-aura` once it reaches `DAILY_STREAK_REWARD_THRESHOLD`.
- **Account deletion**: any `delete_user` flow must call `refresh_weekly_daily_rewards(current_week_start)` after the deletion to reseat the weekly champion holder set.

`emerald-aura` is backfill-only (no live detector). `violet-aura` has no automatic detector and is granted exclusively via the admin endpoint.

### REST endpoints

Player (`/api/rewards`):

```
GET   /api/rewards/catalog                # public catalog: badges + name_templates + phantom_skins
GET   /api/rewards/me                     # held badges, unlocked templates, unlocked_phantom_skins, equipped_*
PATCH /api/rewards/me/equipped            # body: {equipped_badge_id?, equipped_name_template_id?, equipped_phantom_skin_id?}
GET   /api/rewards/notifications          # pending (dismissed_at IS NULL)
POST  /api/rewards/notifications/dismiss  # bulk dismiss; 204
```

Admin (`/api/admin`, gated by `require_admin`):

```
POST   /api/admin/users/{user_id}/badges                 body: {badge_id, reason?}
DELETE /api/admin/users/{user_id}/badges/{badge_id}
POST   /api/admin/users/{user_id}/templates              body: {template_id, reason?}
DELETE /api/admin/users/{user_id}/templates/{template_id}
POST   /api/admin/users/{user_id}/skins                  body: {skin_id, reason?}
DELETE /api/admin/users/{user_id}/skins/{skin_id}
```

### WebSocket protocol

`ParticipantInfo` (in `mod/src/core/protocol.rs`) carries an optional `name_template`:

```rust
pub struct NameTemplate {
    pub color: Option<String>,                  // "#E8E6E1"
    pub gradient: Option<(String, String)>,     // ("#FFE9A8","#C8A44E"), the daily_crown template
}

pub struct ParticipantInfo {
    // existing fields...
    pub name_template: Option<NameTemplate>,    // None = treat as default solid color
}
```

Both `name_css` and `background_css` are **web-only** and are not serialized over WS. The mod renders only the color or gradient on the name column. Existing messages (`auth_ok`, `leaderboard_update`) propagate the new field automatically; no new message types.

Equip changes during a race are eventually consistent: the next periodic `leaderboard_update` propagates the new template. No immediate rebroadcast.

The `auth_ok` message also carries an optional `phantom_skin: string | null` field. The server emits the equipped skin id (e.g. `"gold-aura"`), or `null` when the user has nothing equipped or the equipped value is the literal `"none"`. The translation `none -> null` happens in the WebSocket payload builder via `resolve_phantom_skin_for_auth_ok` in `websocket/schemas.py`. The mod resolves the name to a SpEffect via `graph.json` per the phantom skins integration spec; the field is unused by the racing platform itself.

### Mod rendering

In `mod/src/dll/ui.rs`, the `NameTemplate` is parsed once on receipt and cached per `ParticipantId` in a `HashMap` (hex strings → packed colors). Per-frame the renderer:

- Solid color: writes the cached color on the name column.
- Gradient: char-by-char rendering with linear interpolation between the two cached colors. Pure float ops, no allocations.

Status colors (yellow/white/green/grey for ready/playing/finished/abandoned) remain on the position/layers/IGT columns; the name template only affects the name column itself.

---

## Frontend (Web)

### Username and row rendering

`UserLink.svelte` is the default rendering component for player names. Containers that need a custom row layout (race `Leaderboard.svelte`, `LeaderboardOverlay.svelte`, `ParticipantCard.svelte`, `RewardsPicker.svelte`, `ChatPanel.svelte`, `user/[username]/+page.svelte`) inline the same template-resolution logic rather than wrapping `UserLink`. The duplication is intentional (matches the project's inline-over-helpers convention); when changing the rendering rule, update all consumers.

UserLink:

- Always applies the user's name template `color` or `gradient` (CSS `linear-gradient` + `-webkit-background-clip: text` for gradient text).
- Optional `showBadge?: boolean` prop (default `false`) renders the equipped badge icon (16x16 SVG from `web/static/badges/`) next to the name.

The `background_css` is applied at the **container** level, not in `UserLink`. The visibility model follows the Discord parallel: the name `color`/`gradient` is the "role color" (always visible everywhere it makes sense), the `background_css` is the "profile banner" (visible in showcase contexts, conditional in dense lists).

| Container                                                | Apply `background_css`?                                                        |
| -------------------------------------------------------- | ------------------------------------------------------------------------------ |
| `ParticipantCard.svelte`                                 | always-on (showcase card)                                                      |
| `Leaderboard.svelte` row (race)                          | always-on (short list, 2-8 rows; race context tolerates richness)              |
| `LeaderboardOverlay.svelte` (OBS overlay)                | always-on (consistent with the race view)                                      |
| `WeekLeaderboard.svelte` row (`/daily/[date]` week view) | always-on (short list; the viewer's own row keeps the `.me` highlight instead) |
| `ChatPanel.svelte` messages                              | never (illegible behind chat text)                                             |
| `UserLink` in nav, links, breadcrumbs                    | never (color/gradient only)                                                    |
| Profile gallery preview                                  | always-on (full template preview)                                              |

`ChatPanel.svelte` does not use `UserLink` (the chat row needs role/trait badges and a custom layout), so the name template `color`/`gradient` and the equipped badge icon are inlined in the message header. The chat carries `equipped_badge_id` and `equipped_name_template_id` in `ChatBroadcastMessage` so the frontend can render without a separate lookup.

Readability is owned by the catalog: each template is hand-tuned to contrast adequately with the leaderboard's status colors. No runtime contrast check.

### Settings

`/settings#rewards` exposes two sections:

- **Active Badge**: list of held badges (icon + name + tooltip with `granted_at` and `reason`), an "Equip" button per row, an indicator on the active one, a "Clear" action.
- **Active Name Template**: list of unlocked templates with previews (rendered with the actual `color`/`gradient`/`background_css`), "Activate" button per row, indicator on the active one. `default` is always present.
- **Active Phantom Skin**: grid of cards (one per catalog entry, sorted unlocked-then-locked, ascending sort order within each group). Each card shows a 4:5 portrait screenshot of the skin in-game; locked cards are dimmed with the unlock condition shown as caption. The `none` card is always unlocked and selected by default.

### Dashboard banner

`RewardsBanner.svelte` polls `GET /api/rewards/notifications` and renders a non-blocking banner if pending:

- All `*_granted` / `_unlocked`: "You unlocked N new reward(s) → [View]".
- `badge_revoked`: "You lost the badge X".
- Mixed: "1 unlocked, 1 lost".

"View" or banner click navigates to `/settings#rewards` and POSTs `/api/rewards/notifications/dismiss` (fire-and-forget). The close button dismisses without navigating.

### Profile page

`/user/[id]` exposes a "Rewards" section: a gallery of currently held badges and a gallery of unlocked name templates. Revoked transient badges are not surfaced (rows kept in DB for audit only).

When the user has a phantom skin equipped (other than `none`), the profile avatar slot is replaced by the skin's screenshot at `/phantom_skins/<id>.jpg`; the Twitch avatar remains accessible via the existing Twitch link button in the name row. When no skin is equipped (or `none`), the Twitch avatar shows as before.

### Catalog cache

`GET /api/rewards/catalog` is fetched once per session into a Svelte store, so `UserLink` and container components resolve a `template_id` to its visual definition without duplicating the catalog client-side.

---

## Backfill

`uv run python -m speedfog_racing.scripts.backfill_rewards` is idempotent and is run once after the Alembic migration:

1. Grant `early_adopter` badge, `pioneer` template, and `emerald-aura` phantom skin to every user with `created_at < 2026-04-01`.
2. Grant `archon` template to every user with `role == admin`. Future admin promotions are not auto-granted: an operator manually issues the template via `POST /api/admin/users/{id}/templates`. This is intentional, the case is rare.
3. Grant `veteran` badge, `weathered` template, and `crimson-aura` phantom skin to every user whose count of FINISHED participations is at least `VETERAN_RACE_THRESHOLD`.
4. Grant `frog` badge and `speedfrog` template to every user with at least one FINISHED participation.
5. Grant `molten-aura` phantom skin to every user whose `daily_best_streak` is at least `DAILY_STREAK_REWARD_THRESHOLD`.

The victory rewards are forward-only: no backfill step grants `silver-aura` (race win), `cyan-aura` + `dawnrunner` (daily win), or `gold-aura` + `daily_crown` + `weekly_daily_champion` (weekly champion) retroactively. The next live win or rollup after rollout seeds each player's holder state; historical wins are not replayed.

Each grant emits a `RewardNotification`, so each affected user sees their consolidated banner on their next visit.

---

## Visual Charter (Rewards)

The base graphic charter (`docs/GRAPHIC_CHARTER.md`) governs everything in the app: dark blue-black foundation, warm amber gold (`#C8A44E`) used sparingly, flat design, no gradients, no blur, no textures. Rewards live inside that frame, with two carefully scoped exceptions:

1. **Badges** stay flat (no internal gradients), but use a small thematic palette beyond gold-only, so a wall of badges is readable at a glance.
2. **Name templates** are the **only** components allowed to use gradient fills, translucent backdrops, and alternative typography (text shadow, italic, alternative font family). Their entire purpose is visual differentiation; sober solid colors would defeat them. The "Rage Quit" button is the other documented exception in the existing charter, so this stays consistent with the precedent.

### Exception scope

Name templates are the **only** zone in the app where the rules of `docs/GRAPHIC_CHARTER.md` may be violated, and only on the following dimensions:

- Use of gradients (text and background)
- Use of translucent backdrops
- Use of `text-shadow`, `letter-spacing`, `font-weight` variations, and `font-style: italic`
- Use of `font-family` from a documented short-list of system stacks (sans / serif / mono)

**Everything else in the charter remains binding**, in particular:

- The single-font rule applies to **all UI chrome** (navbar, headings, body, labels, badges, buttons, leaderboard data columns). Only the player's _name itself_, when rendered through a name template, may use an alternative font.
- The "no animation" rule (sole exception: Rage Quit) extends to name templates: no shimmer, no pulse, no animated gradient.
- The color palette outside name templates is unchanged: gold (`#C8A44E`), purple (`#A78BFA`), text colors, semantic status colors, etc.

Name templates are an exception **because** they need to denote. The cost of breaking the charter inside this narrow zone is paid for by the recognition signal it produces. Outside this zone, the charter is the law.

### Badge icon spec

All badges share these constraints:

- **Format**: SVG, `viewBox="0 0 24 24"`, intrinsic size 24x24. Real render size is 16x16 next to the name.
- **Padding**: artwork lives inside a 20x20 box (2px margin on each side) so it does not crop at small sizes.
- **Style**: filled silhouettes only. No internal gradient. No drop shadow. Optional 0.5px stroke in `#0F1923` (background color) for readability over light surfaces.
- **Color count**: one fill per badge by default. A second fill is allowed when the icon depicts a composite physical object whose two parts are naturally distinct in real life (e.g. metal head + wood/dark handle on `contributor`'s hammer). Stay within the same color family for the second fill (a darker shade of the badge's primary color); do not pull arbitrary hues.
- **Detail count**: minimal. 1 to 3 paths per icon. At 16x16 anything finer is mush.
- **Theme**: a clean Elden Ring nod, not a literal asset rip. "Recognizable in a leaderboard row, evocative of the lore."

### Badge palette

Restricted, mapped to badge "kind":

| Use                    | Hex       | Tone                          |
| ---------------------- | --------- | ----------------------------- |
| Champion / top tier    | `#C8A44E` | Gold (charter accent)         |
| Veteran / longevity    | `#9CA3AF` | Steel grey                    |
| Contributor / craft    | `#A78BFA` | Light purple (charter accent) |
| Daily / time-bound     | `#DDB95F` | Light amber                   |
| Early adopter / origin | `#E8E6E1` | Off-white (text primary)      |

Mapping today:

| id                      | fill                                  | rationale                                                                                     |
| ----------------------- | ------------------------------------- | --------------------------------------------------------------------------------------------- |
| `early_adopter`         | `#E8E6E1`                             | Origin / "first light", neutral but not invisible                                             |
| `veteran`               | `#9CA3AF`                             | Endurance, weathered steel                                                                    |
| `contributor`           | `#A78BFA` (head) + `#5B21B6` (handle) | Craft / authorship, ties to charter purple. Bicolor: see exception above                      |
| `weekly_daily_champion` | `#DDB95F`                             | Time-bound gold derivative, the warmest tone in the current badge set                         |
| `weekly_daily_winner`   | `#DDB95F`                             | Same daily/time-bound amber as the champion; distinguished by shape, not color (see concepts) |
| `frog`                  | `#3E9E5C` (body) + `#15391F` (eyes)   | Frog green. Intentional mascot exception, see note below                                      |

No badge currently uses `#C8A44E`: the "Champion / top tier" slot in the palette above is reserved for a future prestige badge but has no live mapping today.

**`frog` is a deliberate exception** to the restricted palette and the "clean Elden Ring nod, not a literal asset" theme. It is a playful brand mascot (Speedfog -> frog), not a prestige or lore marker, so it uses frog green (outside the gold/steel/purple/amber/off-white set) and a literal frog silhouette. Its two fills stay within the same color family (a darker green for the eyes), so the bicolor rule is respected. It is the only mascot-tier badge; new prestige badges must stay within the restricted palette.

**Title easter egg:** when a race title contains the substring "frog" (case-insensitive), the title is tinted frog green (`#3E9E5C`) and prefixed with the `frog.svg` badge on race cards and the race page header. Detection lives in `isFrogTitle` (`web/src/lib/format.ts`); it is purely cosmetic and unrelated to the reward grant above.

### Badge concepts

Each entry below describes the iconographic intent. Implementation files in `web/static/badges/<id>.svg`.

| id                      | concept                                                                                                                                                                                                |
| ----------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `early_adopter`         | Shooting star: 5-point star at upper-right with a trail of 3 decreasing diamond particles toward lower-left                                                                                            |
| `veteran`               | Three stacked chevrons (military rank stripes pointing up), evokes "rank earned through service"                                                                                                       |
| `contributor`           | Tilted war hammer: trapezoidal head with a small triangular pick on one side, thick handle, rotated -25°. The only bicolor badge: head in `#A78BFA`, handle in darker `#5B21B6` for tool-relief depth. |
| `weekly_daily_champion` | Bold sun disk (centered circle, r=5.5) with 7 thick triangular rays reaching toward the edge (one per day of the week). Sized to out-weight the lower-tier winner medal.                               |
| `weekly_daily_winner`   | Prize ribbon: a small medallion disk (r=4) with two thin ribbon tails fanning below it (a single-win motif). Kept lighter than the champion's sun so the higher tier reads as the stronger icon.       |
| `frog`                  | Front-facing frog: wide rounded body, two raised eye bumps on top with dark pupils, a small smile arc. Placeholder flat SVG; may be swapped for a legible in-game frog cutout (PNG) at the same id.    |

`veteran` deliberately avoids any shield silhouette (the `Cautious` play-style trait already uses one); chevrons keep it disjoint. `contributor` is a hammer rather than the originally proposed quill because at 16x16 a feather/quill silhouette degrades into "ambiguous diagonal blade" without legible barbs. `early_adopter`'s trail-of-particles design replaces an earlier "comet trail" attempt that read as a magic wand at small sizes.

### Name template spec

Name templates have four rendering channels, split between cross-platform (replicated by the in-game mod) and web-only escape hatches.

| Channel          | Cross-platform    | Required                         | Notes                                                                                                                                                              |
| ---------------- | ----------------- | -------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `color`          | yes               | Either `color` **or** `gradient` | Solid hex, e.g. `#E8E6E1`. Used for name text.                                                                                                                     |
| `gradient`       | yes               | Either `color` **or** `gradient` | Two-stop tuple, e.g. `("#FFE9A8", "#C8A44E")`. Used for name text via `linear-gradient` + `-webkit-background-clip: text`. The mod replicates this glyph by glyph. |
| `name_css`       | **no (web-only)** | Optional                         | Raw CSS string applied as inline style on the name span (e.g. `text-shadow`, `font-style`, `letter-spacing`). See [name_css allowlist](#name_css-allowlist) below. |
| `background_css` | **no (web-only)** | Optional                         | Raw CSS `background` value. Applied at container level by the consumer (see [Username and row rendering](#username-and-row-rendering)).                            |

The `color`/`gradient` pair is the **cross-platform contract**: the mod overlay receives the resolved values via WebSocket and renders them in-game, glyph by glyph. `name_css` and `background_css` are **web-only escape hatches**: never serialized over WebSocket, never replicated by the mod. A streamer's OBS overlay (which is a web view) does apply both, so viewers do see the full effect.

#### name_css allowlist

`name_css` is a raw CSS string. Authors are expected to limit themselves to the following properties. There is no runtime check; this is a discipline contract enforced at code review time on the catalog file.

**Accepted**:

- `text-shadow`
- `letter-spacing`
- `text-decoration` (no `blink`, no `wavy`)
- `font-weight` (limited to `400` / `500` / `600` / `700`, the Inter weights bundled by the app)
- `font-style` (`normal` | `italic`)
- `font-family` **only** among:
  - `Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif` (charter default; same stack as the rest of the UI)
  - `Georgia, "Times New Roman", Times, serif` (lore / champion-tier)
  - `ui-monospace, "SF Mono", Menlo, Consolas, "Courier New", monospace` (technical / dev-tier)

System fonts only. No web font loading (avoids network cost, FOIT/FOUT, and third-party tracking concerns).

**Forbidden** (would break layout or violate the charter):

- `font-size` (breaks alignment of leaderboard rows; the chrome owns the size)
- `font-family` outside the three stacks above
- `display`, `position`, `z-index`, `transform`, `float`
- `text-transform` (alters the user's identity, breaks search)
- `animation`, `transition` (charter forbids animations everywhere except the Rage Quit button)
- `width`, `height`, `margin`, `padding` (chrome owns the box model)

#### Visual rules

- **Always validate against a dark surface** (`--color-surface` `#162032` and `--color-surface-elevated` `#1C2A3F`). The leaderboard, participant cards, and OBS overlay all sit on these backgrounds.
- **Backgrounds stay subtle**. The row already carries status, position, and IGT information; the template should accent the name, not drown the data. Aim for an integrated alpha of `0.14` to `0.20`. Above that, status colors and rank numbers lose contrast.
- **Prefer warm radial highlights** behind the name over flat horizontal gradients across the full row. A `radial-gradient(ellipse 60% 100% at 25% 50%, ...)` reads as "the name glows", whereas a 90deg gradient flattens the row visually.
- **Two-stop gradients only**, no rainbows. The template's identity should be readable as one color family.
- **Don't combine too many cues**. A template that stacks gradient text + heavy shadow + alternate font + dense backdrop reads as visual noise. Pick one or two strong signals; keep the rest discreet.
- **Hierarchy by tier**. A higher-tier template should have a _qualitatively_ different signal from a lower one (different font family, not just a slightly different color). This keeps the recognition gradient legible: a quick glance should distinguish `daily_crown` from `dawnrunner` without reading the pseudonym.

#### Italic + gradient WebKit gotcha

When a template combines `gradient` (rendered via `background-clip: text` + `color: transparent`) with `font-style: italic`, the slanted right edge of the last glyph extends past the text's bounding box, where the gradient is no longer painted, so the last letter appears partially clipped. The gradient code path in every name-rendering component appends `padding-inline-end: 0.1em` to compensate. New components that resolve a name template's gradient inline must do the same. This is intentionally **not** in the `name_css` allowlist: it is a rendering-engine workaround, not a template author's design choice.

### Name template catalog

| id            | text gradient                          | name_css                                                                                                                                                              | background_css                                                                            | rationale                                                                                                                                                                                                                                                                                                                                                                                                                                                        |
| ------------- | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `default`     | Solid `#E8E6E1` (charter primary text) | none                                                                                                                                                                  | none                                                                                      | Charter primary text. Always available, never revocable.                                                                                                                                                                                                                                                                                                                                                                                                         |
| `daily_crown` | `("#FFE9A8", "#C8A44E")`               | `font-style: italic; font-weight: 600; text-shadow: 0 0 4px rgba(168, 139, 92, 0.28);`                                                                                | `radial-gradient(ellipse 60% 100% at 25% 50%, rgba(200, 164, 78, 0.18), transparent 70%)` | Weekly champion souvenir. Inter italic semi-bold + warm gold gradient + bronze halo produces a "tarnished gold" effect, very ER-flavored (the player is a Tarnished). Shares Inter italic with `dawnrunner` so the pair reads as one family: the daily-victory axis, gold for the week.                                                                                                                                                                          |
| `dawnrunner`  | `("#A8DCE9", "#4E9EC8")`               | `font-style: italic; font-weight: 600; text-shadow: 0 0 5px rgba(168, 220, 233, 0.28);`                                                                               | `radial-gradient(ellipse 60% 100% at 25% 50%, rgba(78, 158, 200, 0.14), transparent 70%)` | Daily win souvenir. Same Inter italic semi-bold family as `daily_crown`, in cyan instead of gold: the pair reads as the daily-victory axis at two scopes, gold for topping the week, cyan for winning a single day. Both stops sit fully in the cyan-blue family (no off-white start) so the pseudo reads "cyan" end-to-end, including in the in-game mod overlay where italic and shadow are not applied.                                                       |
| `pioneer`     | _(none, default text color)_           | `font-family: Georgia, "Times New Roman", Times, serif; font-style: italic; font-weight: 600; letter-spacing: 0.02em; text-shadow: 0 0 6px rgba(200, 164, 78, 0.35);` | `radial-gradient(ellipse 50% 80% at 25% 50%, rgba(232, 220, 196, 0.12), transparent 60%)` | Early adopter souvenir. **Intentionally no gradient**: in the in-game mod overlay (which only reads `color`/`gradient`) the pseudo keeps its status color, so the marker is web-only and never overrides active race signals. On the web, Georgia italic semi-bold + gold halo on a parchment backdrop reads as "veteran scroll". Backdrop is the most discreet of the catalog (alpha `0.12`, smaller ellipse) since this is a broad-tier souvenir worn by many. |
| `weathered`   | `("#D4A574", "#A06A35")`               | `font-weight: 500; letter-spacing: 0.02em; text-shadow: 0 0 4px rgba(160, 106, 53, 0.28);`                                                                            | `radial-gradient(ellipse 60% 100% at 25% 50%, rgba(160, 106, 53, 0.14), transparent 70%)` | Veteran tenure souvenir. Warm bronze gradient + Inter medium (no italic, no serif, no font swap) reads as "patinated / battle-worn" without competing with the daily-victory templates' italic+semi-bold axis or the lore templates' serif axis. The lighter weight keeps it as a discreet souvenir rather than a prestige marker, and the warm bronze hue is fully disjoint from `dawnrunner`'s cool cyan to avoid any cross-reading at a glance.               |
| `archon`      | `("#C4B5FD", "#7C3AED")`               | `font-family: ui-monospace, "SF Mono", Menlo, Consolas, "Courier New", monospace; font-weight: 600; text-shadow: 0 0 6px rgba(124, 58, 237, 0.35);`                   | `radial-gradient(ellipse 60% 100% at 25% 50%, rgba(124, 58, 237, 0.18), transparent 70%)` | Administrator marker. Mono semi-bold in charter purple; the only template using the mono font slot. Visually unambiguous at a glance and disjoint from the serif italic "champion" axis (`daily_crown`), so the two top-tier signals do not compete.                                                                                                                                                                                                             |

**Note on color tuning**: cool-toned templates (e.g. `dawnrunner`'s cyan-blue) need stronger pigmentation than warmer-tone templates. The default text color `#E8E6E1` is itself a warm off-white; any template gradient with stops near that value will read as plain default text in renderers without backdrop support (the in-game mod). Templates in distant color families (gold, crimson, emerald) tolerate a brighter / more washed-out start stop because the hue itself differentiates from default. Templates in cool greys, off-whites, or pale tones must pick stops that are _fully saturated_ in their family.

### Adding a new reward (checklist)

1. Decide kind (badge or name template) and lifecycle (permanent / transient for badges; permanent only for templates).
2. Pick an id (`snake_case`, stable, never renamed).
3. Add a catalog entry in `catalog.py` with `name`, `description`, `sort_order`, and visual fields.
4. For badges: produce an SVG following the [Badge icon spec](#badge-icon-spec), drop it under `web/static/badges/<icon_filename>`.
5. For name templates: validate the `color`/`gradient`, `name_css`, and `background_css` against dark surfaces (`#162032`, `#1C2A3F`) using a real leaderboard preview. Confirm `name_css` properties stay within the [allowlist](#name_css-allowlist).
6. If the reward has an automatic source: wire the detector in the appropriate service (`race_lifecycle.py`, `daily_seed_loop.py`, etc.) using `RewardsService.refresh_*` or `sync_transient_holders`.
7. If permanent and historically applicable: extend `scripts/backfill_rewards.py`.
8. Update this document's catalog tables.

---

## Testing

### Backend

- `rewards/test_service.py`:
  - `grant_permanent_badge`: idempotence, lifecycle mismatch, notification on creation only.
  - `grant_name_template`: idempotence, notification on creation only, `default` skipped.
  - `sync_transient_holders`: diff correctness, atomicity, ties, auto-clear of `equipped_badge_id`, both `badge_granted` and `badge_revoked` notifications.
  - `set_equipped_badge` / `set_equipped_name_template`: rejects unowned ids, accepts `null`, accepts `default`.
  - `dismiss_notifications`: bulk update, idempotent, returns count.
- `api/test_rewards.py`: GET inventory, PATCH equipped (success and failure paths), GET/POST notifications, GET catalog (no admin-only fields leaked).
- `api/test_admin_rewards.py`: admin endpoints gated by `require_admin`; admin grant emits notification, admin revoke does not.
- Integration: a finished public race triggers `grant_race_win_rewards` (silver-aura to the winner); a closed daily triggers `grant_daily_win_rewards` (cyan-aura + dawnrunner, ties included); the Monday `daily_seed_loop` rollup triggers `refresh_weekly_daily_rewards` (weekly_daily_champion + gold-aura + daily_crown to the week's top scorer(s)).

### Frontend (Vitest)

- `UserLink.svelte`: solid color, gradient, with/without badge.
- `RewardsBanner.svelte`: granted-only, revoked-only, mixed; dismiss flow.
- Settings rewards section: equip / unequip; "active" indicator.

### Mod (Rust)

- `protocol.rs` deserialization for `name_template` in `auth_ok` and `leaderboard_update` (`Some(solid)`, `Some(gradient)`, `None`).
- Manual smoke test for the gradient render in-game; no automated visual test.
