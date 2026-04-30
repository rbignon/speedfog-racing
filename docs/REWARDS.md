# Rewards System

Source-agnostic cosmetic recognition for SpeedFog Racing players. Two reward types:

- **Badges**: small icons displayed next to a player's name in leaderboards, chat, and profile cards.
- **Name templates**: visual customization of the player's name (color or gradient) and, in selected containers, of the surrounding row or card background.

Rewards are decoupled from any specific source: a badge can be granted by an admin, attributed automatically by an in-process detector (top 1 ELO holder, weekly daily champion), or filled in by a backfill script. Rewards are purely cosmetic, never tradable, and never affect gameplay or matchmaking.

The original design rationale lives in [`docs/specs/2026-04-30-rewards-system-design.md`](specs/2026-04-30-rewards-system-design.md). This document is the operational reference: what the system does today, how it is wired, and what the visual artifacts should look like.

---

## Functional Overview

### Catalog

The catalog is static Python configuration in [`server/speedfog_racing/rewards/catalog.py`](../server/speedfog_racing/rewards/catalog.py). Adding a reward is a code change followed by a deploy. There is no admin UI for catalog editing, on purpose: the catalog is small enough that drift between code and DB would cost more than it saves.

#### Badges

| id                      | name           | lifecycle | source                                                                        |
| ----------------------- | -------------- | --------- | ----------------------------------------------------------------------------- |
| `early_adopter`         | Early Adopter  | permanent | Backfill: accounts created before `2026-04-01`.                               |
| `veteran`               | Veteran        | permanent | Auto: granted on the first race finish past `N` total races.                  |
| `contributor`           | Contributor    | permanent | Admin grant only.                                                             |
| `top1_elo`              | ELO Champion   | transient | Auto: holder(s) of the highest ELO with `elo_races >= PROVISIONAL_THRESHOLD`. |
| `weekly_daily_champion` | Daily Champion | transient | Auto: most daily wins over the previous Mon-Sun week.                         |

Lifecycle:

- **Permanent**: granted once, kept forever (admin can revoke as a mistake-correction escape hatch).
- **Transient**: holder set is recomputed from an external condition; revoked when the player no longer meets it.

Ties are allowed: when the qualifying condition selects multiple players (e.g. several users tied at the highest ELO), all of them hold the badge simultaneously.

#### Name templates

| id           | description                          | unlock                                                                                                                                                         |
| ------------ | ------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `default`    | Solid white name                     | Always unlocked, never revocable                                                                                                                               |
| `elo_crown`  | Gold gradient + warm gold backdrop   | Granted permanently the first time a player reaches top 1 ELO                                                                                                  |
| `runebearer` | Silver gradient (top 5 ELO souvenir) | Planned: granted permanently the first time a player enters the top 5 ELO. Currently only available via admin grant; the auto-detection hook is not yet wired. |

Name templates are **always permanent**. Once unlocked, they remain unlocked even if the player no longer meets the original condition (the gold-on-the-name memento outlasts the dynamic badge).

### Equip rules

- A player has at most **one badge equipped**. Slot can be empty.
- A player has exactly **one name template active**. Defaults to `default` (solid white) if nothing is set, or if the equipped one is revoked.
- When a transient badge is revoked from a player who had it equipped, the equip slot is auto-cleared. The corresponding `elo_crown` / `runebearer` souvenir name template stays unlocked.

### Notifications

Each grant, revoke, or unlock writes a row in `reward_notifications`. The dashboard banner (`RewardsBanner.svelte`) reads pending notifications, summarizes them, and points the user to `/settings#rewards`. Click-through (or explicit dismiss) clears all pending notifications for that user.

Admin revokes do **not** emit notifications: they are mistake corrections, not events.

---

## Data Model

Three tables, plus two scalar columns on `users`.

### `users` (added columns)

| column                      | type              | notes                                                              |
| --------------------------- | ----------------- | ------------------------------------------------------------------ |
| `equipped_badge_id`         | `String(50) NULL` | Logical key into the `BADGES` catalog                              |
| `equipped_name_template_id` | `String(50) NULL` | Logical key into `NAME_TEMPLATES`. `NULL` resolves to `"default"`. |

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

### `reward_notifications`

| column         | type                                                             | notes                |
| -------------- | ---------------------------------------------------------------- | -------------------- |
| `id`           | UUID PK                                                          |                      |
| `user_id`      | UUID FK, indexed                                                 |                      |
| `kind`         | Enum(`badge_granted`, `badge_revoked`, `name_template_unlocked`) |                      |
| `reward_id`    | `String(50)`                                                     |                      |
| `created_at`   | `DateTime(tz=True)`                                              |                      |
| `dismissed_at` | `DateTime(tz=True) NULL`                                         | `NULL` means pending |

---

## Server Architecture

```
server/speedfog_racing/
  rewards/
    __init__.py
    catalog.py          # BADGES, NAME_TEMPLATES dicts (frozen dataclasses)
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
- `refresh_top1_elo_holders(reason=None)`: queries the top ELO from `users` (filtered by `elo_races >= PROVISIONAL_THRESHOLD`), syncs `top1_elo`, then idempotently grants `elo_crown` to each holder.
- `refresh_weekly_daily_champion(week_starting: date, reason=None)`: aggregates daily wins over `[week_starting, week_starting + 7d)`, syncs `weekly_daily_champion` to the top winner(s).
- `set_equipped_badge(user_id, badge_id: str | None)`: validates ownership, updates `users.equipped_badge_id`. Raises `NotOwnedError` if the user does not currently hold the badge.
- `set_equipped_name_template(user_id, template_id: str | None)`: validates ownership (`default` is always allowed), updates `users.equipped_name_template_id`.
- `get_user_inventory(user_id) -> Inventory`: held badges + unlocked templates + equip state, sorted by `sort_order`.
- `get_pending_notifications(user_id)`, `dismiss_notifications(user_id)`: banner read/clear.
- `revoke_badge(user_id, badge_id)`, `revoke_name_template(user_id, template_id)`: admin escape hatches. Auto-clear matching equip slots. Do **not** emit notifications.

### Integration points

- **Top 1 ELO** (`services/race_lifecycle.py`): after each `update_elo_ratings(...)` call, invoke `refresh_top1_elo_holders()`. The `runebearer` (top 5) auto-grant is planned to live next to this hook but is not yet wired (see [Top 5 ELO unlock](#top-5-elo-unlock-planned) below).
- **Weekly daily champion** (`services/daily_seed_loop.py`): when generating a daily seed for a Monday, call `refresh_weekly_daily_champion(week_starting=monday-7d)`. Past weeks before the rollout are not backfilled.
- **Account deletion**: any `delete_user` flow must call `refresh_top1_elo_holders()` and `refresh_weekly_daily_champion(current_week_start)` after the deletion to reseat the holder sets.

#### Top 5 ELO unlock (planned)

`runebearer` is intended as a permanent souvenir for any player who has entered the top 5 ELO at least once. The wiring is **not yet implemented**: the catalog entry exists, but no detection hook grants it automatically. Admins can grant it manually in the meantime via the existing `POST /api/admin/users/{user_id}/templates` endpoint.

When the auto-grant lands, the natural place is alongside `refresh_top1_elo_holders`: after computing the top ELO holders, fetch the top 5 (filtered by `elo_races >= PROVISIONAL_THRESHOLD`, ordered by `elo_rating DESC`) and idempotently call `grant_name_template(user_id, "runebearer")` for each. The two unlocks (`elo_crown` and `runebearer`) would remain independent: a player who reaches top 1 directly receives both; a player who only ever floats around #3-#5 keeps `runebearer` for life.

### REST endpoints

Player (`/api/rewards`):

```
GET   /api/rewards/catalog                # public catalog (id, name, description, color, gradient, background_css, icon_filename)
GET   /api/rewards/me                     # held badges, unlocked templates, equipped_*
PATCH /api/rewards/me/equipped            # body: {equipped_badge_id?, equipped_name_template_id?}
GET   /api/rewards/notifications          # pending (dismissed_at IS NULL)
POST  /api/rewards/notifications/dismiss  # bulk dismiss; 204
```

Admin (`/api/admin`, gated by `require_admin`):

```
POST   /api/admin/users/{user_id}/badges                 body: {badge_id, reason?}
DELETE /api/admin/users/{user_id}/badges/{badge_id}
POST   /api/admin/users/{user_id}/templates              body: {template_id, reason?}
DELETE /api/admin/users/{user_id}/templates/{template_id}
```

### WebSocket protocol

`ParticipantInfo` (in `mod/src/core/protocol.rs`) carries an optional `name_template`:

```rust
pub struct NameTemplate {
    pub color: Option<String>,                  // "#E8E6E1"
    pub gradient: Option<(String, String)>,     // ("#FFE9A8","#C8A44E") — the elo_crown template
}

pub struct ParticipantInfo {
    // existing fields...
    pub name_template: Option<NameTemplate>,    // None = treat as default solid color
}
```

Both `name_css` and `background_css` are **web-only** and are not serialized over WS. The mod renders only the color or gradient on the name column. Existing messages (`auth_ok`, `leaderboard_update`) propagate the new field automatically; no new message types.

Equip changes during a race are eventually consistent: the next periodic `leaderboard_update` propagates the new template. No immediate rebroadcast.

### Mod rendering

In `mod/src/dll/ui.rs`, the `NameTemplate` is parsed once on receipt and cached per `ParticipantId` in a `HashMap` (hex strings → packed colors). Per-frame the renderer:

- Solid color: writes the cached color on the name column.
- Gradient: char-by-char rendering with linear interpolation between the two cached colors. Pure float ops, no allocations.

Status colors (yellow/white/green/grey for ready/playing/finished/abandoned) remain on the position/layers/IGT columns; the name template only affects the name column itself.

---

## Frontend (Web)

### Username and row rendering

`UserLink.svelte` is the default rendering component for player names. Containers that need a custom row layout (race `Leaderboard.svelte`, `LeaderboardOverlay.svelte`, `ParticipantCard.svelte`, `RewardsTemplatePicker.svelte`, `stats/LeaderboardTab.svelte`, `ChatPanel.svelte`, `user/[username]/+page.svelte`) inline the same template-resolution logic rather than wrapping `UserLink`. The duplication is intentional (matches the project's inline-over-helpers convention); when changing the rendering rule, update all consumers.

UserLink:

- Always applies the user's name template `color` or `gradient` (CSS `linear-gradient` + `-webkit-background-clip: text` for gradient text).
- Optional `showBadge?: boolean` prop (default `false`) renders the equipped badge icon (16x16 SVG from `web/static/badges/`) next to the name.

The `background_css` is applied at the **container** level, not in `UserLink`. The visibility model follows the Discord parallel: the name `color`/`gradient` is the "role color" (always visible everywhere it makes sense), the `background_css` is the "profile banner" (visible in showcase contexts, conditional in dense lists).

| Container                                    | Apply `background_css`?                                           |
| -------------------------------------------- | ----------------------------------------------------------------- |
| `ParticipantCard.svelte`                     | always-on (showcase card)                                         |
| `Leaderboard.svelte` row (race)              | always-on (short list, 2-8 rows; race context tolerates richness) |
| `LeaderboardOverlay.svelte` (OBS overlay)    | always-on (consistent with the race view)                         |
| `stats/LeaderboardTab.svelte` row (`/stats`) | always-on for **rows 1-3** (podium); **hover-only** for rows 4+   |
| `ChatPanel.svelte` messages                  | never (illegible behind chat text)                                |
| `UserLink` in nav, links, breadcrumbs        | never (color/gradient only)                                       |
| Profile gallery preview                      | always-on (full template preview)                                 |

`ChatPanel.svelte` does not use `UserLink` (the chat row needs role/trait badges and a custom layout), so the name template `color`/`gradient` and the equipped badge icon are inlined in the message header. The chat carries `equipped_badge_id` and `equipped_name_template_id` in `ChatBroadcastMessage` so the frontend can render without a separate lookup.

#### `/stats` podium + hover behavior

The split between always-on (top 3) and hover-only (rows 4+) is implemented at the row level:

- Rows 1-3 receive the row's `style="background: <background_css>"` unconditionally.
- Rows 4+ render `background: transparent` by default and switch to the template's `background_css` on `:hover` (and on `:focus-within` for keyboard nav).
- The transition uses the charter's `--transition: 0.2s ease`, applied to `background` only, so a hovered row reveals its background without jarring the eye on a long scroll.

Rationale: a /stats leaderboard can carry 50-100 rows; stacking translucent backdrops on every row would drown the numeric data (rank, ELO, runs) that the page exists to expose. Keeping the podium always-on preserves the "gold appears as punctuation" charter principle (top of the list = enriched), while hover-on-the-rest converts the background into a discovery affordance similar to a Discord profile banner.

Readability is owned by the catalog: each template is hand-tuned to contrast adequately with the leaderboard's status colors. No runtime contrast check.

### Settings

`/settings#rewards` exposes two sections:

- **Active Badge**: list of held badges (icon + name + tooltip with `granted_at` and `reason`), an "Equip" button per row, an indicator on the active one, a "Clear" action.
- **Active Name Template**: list of unlocked templates with previews (rendered with the actual `color`/`gradient`/`background_css`), "Activate" button per row, indicator on the active one. `default` is always present.

### Dashboard banner

`RewardsBanner.svelte` polls `GET /api/rewards/notifications` and renders a non-blocking banner if pending:

- All `*_granted` / `_unlocked`: "You unlocked N new reward(s) → [View]".
- `badge_revoked`: "You lost the badge X".
- Mixed: "1 unlocked, 1 lost".

"View" or banner click navigates to `/settings#rewards` and POSTs `/api/rewards/notifications/dismiss` (fire-and-forget). The close button dismisses without navigating.

### Profile page

`/user/[id]` exposes a "Rewards" section: a gallery of currently held badges and a gallery of unlocked name templates. Revoked transient badges are not surfaced (rows kept in DB for audit only).

### Catalog cache

`GET /api/rewards/catalog` is fetched once per session into a Svelte store, so `UserLink` and container components resolve a `template_id` to its visual definition without duplicating the catalog client-side.

---

## Backfill

`uv run python -m speedfog_racing.scripts.backfill_rewards` is idempotent and is run once after the Alembic migration:

1. Grant `early_adopter` to every user with `created_at < 2026-04-01`.
2. Run `refresh_top1_elo_holders()` to grant the current top 1 ELO badge and the `elo_crown` template. The `runebearer` (top 5) auto-grant is not yet wired and will be added when the detection hook lands.
3. Skip historical weekly daily champions (the badge is transient; backfilling past weeks would conflict with the "current holder" semantics).

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

| id                      | fill      | rationale                                             |
| ----------------------- | --------- | ----------------------------------------------------- |
| `early_adopter`         | `#E8E6E1` | Origin / "first light", neutral but not invisible     |
| `veteran`               | `#9CA3AF` | Endurance, weathered steel                            |
| `contributor`           | `#A78BFA` | Craft / authorship, ties to charter purple            |
| `top1_elo`              | `#C8A44E` | Champion = the only true gold use in the badge set    |
| `weekly_daily_champion` | `#DDB95F` | Time-bound gold derivative, subordinate to `top1_elo` |

The `top1_elo` icon is the **only** badge using `#C8A44E`. This keeps the charter's "gold appears sparingly as punctuation" principle intact: the top ELO holder is the one place where gold marks a person, just as it marks the #1 leaderboard rank elsewhere.

### Badge concepts

Each entry below describes the iconographic intent. Implementation files in `web/static/badges/<id>.svg`.

| id                      | concept                                                     |
| ----------------------- | ----------------------------------------------------------- |
| `early_adopter`         | Stylized Erdtree leaf, single silhouette                    |
| `veteran`               | Faceted shield with a small notch (battle-worn, simple)     |
| `contributor`           | Quill stroke shaped to suggest both writing and a flame tip |
| `top1_elo`              | 3-fleuron crown, symmetrical, no decorative jewels          |
| `weekly_daily_champion` | Sun disk with 7 short rays (one per day of the week)        |

The current SVGs are placeholders and need to be redrawn against this spec. The `top1_elo` placeholder uses `#FFD700` (pure yellow) which is brighter than the charter's warm amber `#C8A44E`; this needs to be corrected during the rework.

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
- **Hierarchy by tier**. A higher-tier template should have a _qualitatively_ different signal from a lower one (different font family, not just a slightly different color). This keeps the recognition gradient legible: a quick glance should distinguish `elo_crown` from `runebearer` without reading the pseudonym.

### Name template catalog

| id           | text gradient                          | name_css                                                                                                                                            | background_css                                                                             | rationale                                                                                                                                                                                                                                                                                                                                                                                                           |
| ------------ | -------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `default`    | Solid `#E8E6E1` (charter primary text) | none                                                                                                                                                | none                                                                                       | Charter primary text. Always available, never revocable.                                                                                                                                                                                                                                                                                                                                                            |
| `elo_crown`  | `("#FFE9A8", "#C8A44E")`               | `font-family: Georgia, "Times New Roman", Times, serif; font-style: italic; letter-spacing: 0.02em; text-shadow: 0 0 6px rgba(200, 164, 78, 0.35);` | `radial-gradient(ellipse 60% 100% at 25% 50%, rgba(200, 164, 78, 0.18), transparent 70%)`  | Champion souvenir. Serif italic + warm gold + soft glow evokes the lore typography of the Lands Between. Strongest tier signal in the catalog.                                                                                                                                                                                                                                                                      |
| `runebearer` | `("#B8C5D6", "#6F87A6")`               | `font-style: italic; text-shadow: 0 0 5px rgba(184, 197, 214, 0.28);`                                                                               | `radial-gradient(ellipse 60% 100% at 25% 50%, rgba(184, 197, 214, 0.14), transparent 70%)` | Top 5 ELO souvenir. Same Inter font as default; the silver gradient + italic + faint blue glow differentiate it without reaching for serif typography. Both gradient stops sit fully in the silver-blue family (no off-white start) so the pseudo reads "silver" end-to-end, including in the in-game mod overlay where italic and shadow are not applied. Keeps the tier gap with `elo_crown` legible at a glance. |

**Note on color tuning**: silver-blue templates need stronger pigmentation than warmer-tone templates. The default text color `#E8E6E1` is itself a warm off-white; any template gradient with stops near that value will read as plain default text in renderers without backdrop support (the in-game mod). Templates in distant color families (gold, crimson, emerald) tolerate a brighter / more washed-out start stop because the hue itself differentiates from default. Templates in cool greys, off-whites, or pale tones must pick stops that are _fully saturated_ in their family.

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
- Integration: a finished race triggers `top1_elo` resync against a mocked ELO state; `daily_seed_loop` rollup at a Monday boundary.

### Frontend (Vitest)

- `UserLink.svelte`: solid color, gradient, with/without badge.
- `RewardsBanner.svelte`: granted-only, revoked-only, mixed; dismiss flow.
- Settings rewards section: equip / unequip; "active" indicator.

### Mod (Rust)

- `protocol.rs` deserialization for `name_template` in `auth_ok` and `leaderboard_update` (`Some(solid)`, `Some(gradient)`, `None`).
- Manual smoke test for the gradient render in-game; no automated visual test.
