# Dashboard Redesign

## Summary

Replace the personalized homepage with a dedicated `/dashboard` page for logged-in users. The homepage (`/`) becomes identical for everyone (hero DAG + public races). The dashboard is a personal space: contextual stats, active sessions, and recent activity.

## Routing Changes

- **New page `/dashboard`** — logged-in users only, redirects to `/` if anonymous.
- **Homepage `/`** — identical for all users: hero DAG + CTA + public races (live + upcoming). Remove all `isLoggedIn` conditional rendering.
- **Post-login redirect** — auth callback redirects to `/dashboard` instead of `/`.
- **Navbar** — logo links to `/dashboard` (logged in) or `/` (anonymous). Add "Races" link in navbar pointing to `/` for logged-in users to access public race listing.

## Dashboard Layout (Vertical Stack)

### Section 1: Stats

Grid layout — 3 columns desktop, 2 columns mobile.

**Row 1 — Totals (3 cards):**

- Races (count)
- Trainings (count)
- Podiums (count)

**Row 2 — Contextual (2 wider cards):**

- **Best recent placement**: medal icon (gold/silver/bronze) + placement + race name + relative timestamp. Empty state: "No podium yet".
- **Podium rate**: percentage + fraction (e.g., "40% (4/10)"). Empty state: "—" if 0 races.

### Section 2: Active Now

Full-width stacked cards. Each card is entirely clickable (link to `/race/{id}` or `/training/{id}`).

**Card contents:**

- Line 1: status badge (colored) + name + player count (races only)
- Line 2: IGT + deaths
- Line 3: progress bar (current_layer / total_layers) with "Layer X/Y" label

**Styling:** gold border for races, standard border for training.

**Empty state:** "No active sessions" + CTA buttons:

- Organizer/admin: "Create Race" + "Start Training"
- Regular user: "Start Training"

### Section 3: Recent Activity

List of 5 most recent activities.

**Each row:**

- Icon/badge by type (colored placement for races, training icon, mic icon for casts)
- Event name (clickable link to race/training page)
- Relative timestamp (right-aligned)
- Details: placement/total or DNF (races), pool name (training), race name (casts)

**Footer:** "See all activity" link → `/user/{username}` (profile page)

## API Changes

### `GET /users/{username}` — add fields

- `podium_rate: float | null` — podium_count / race_count, null if 0 races
- `best_recent_placement: object | null` — `{ placement, race_name, race_id, finished_at }`, best placement among last 10 finished races, null if no finished races

### `GET /users/me/races` — add fields (active races only)

- `current_layer: int` — current tier/layer in the seed graph
- `total_layers: int` — total tiers in the seed graph

### `GET /training` — add fields (active training only)

- `current_layer: int` — current tier/layer in the seed graph
- `total_layers: int` — total tiers in the seed graph

## Frontend Changes

- **New:** `web/src/routes/dashboard/+page.svelte`
- **Simplify:** `web/src/routes/+page.svelte` — remove logged-in conditional, keep hero + public races only
- **Update:** `web/src/routes/+layout.svelte` — logo link conditional, add "Races" navbar link
- **Update:** `web/src/routes/auth/callback/+page.svelte` — default redirect to `/dashboard`
- **Update:** `web/src/lib/api.ts` — update types for new API fields

## Design Decisions

- Dashboard is purely personal — no public races shown.
- Stats are contextual (progression-oriented), not just cumulative totals.
- Recent activity is limited to 5 items to avoid duplicating the profile's full timeline.
- Progress bar on active cards gives instant visual feedback without opening the session.
- Homepage simplification removes ~50% of the homepage code (all auth-conditional rendering).
