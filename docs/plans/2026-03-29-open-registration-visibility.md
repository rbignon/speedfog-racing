# Open Registration Visibility

**Date:** 2026-03-29
**Goal:** Make it obvious that open-registration races can be joined, through three coordinated UI changes and one new API endpoint.

## Context

Open-registration races allow any logged-in player to join without an invite. Currently, there is no visual distinction between open and invite-only races on race cards, the race list, or the dashboard. The user must navigate to the race detail page to discover the "Join Race" button. This spec adds three features to surface joinability earlier.

## Feature 1: Navbar Badge

A small count pill on the "Races" button in the navbar, showing the number of joinable open-registration races.

**Behavior:**

- Visible only when the user is logged in (the "Races" button itself is only shown when logged in)
- Count = number of open-registration races in `setup` status where the user is not organizer, participant, or caster, and the race is not full
- Hidden when count is 0
- Pill style: green background (`--color-success`), dark text, positioned top-right of the "Races" button (same style as the existing "Beta" badge but smaller and round)

**Data source:** `GET /api/races/joinable` (see API section). The layout fetches this on mount and uses `races.length` for the count.

## Feature 2: RaceCard Open Badge + Join CTA

Two additions to the RaceCard component when a race is joinable:

### "Open" Badge

- Green badge (same style as existing status badges) with text "Open", placed in the badges row next to the status badge
- Shown when `open_registration === true` and `status === 'setup'`
- Visible to all users (logged in or not), since it describes the race's registration mode

### "Join" Button

- Outlined button with green border and text (`border: 1px solid var(--color-success); color: var(--color-success)`), text "Join" (no arrow)
- Positioned in the avatar row, center (same position as the winner trophy+name on finished cards)
- Purely a visual CTA; clicking it navigates to the race detail page (same as clicking anywhere on the card)
- Shown only when the user is logged in, the race is joinable (open, setup, not full), and the user is not already organizer/participant/caster
- When `max_participants` is set, the player count in the meta row shows "3/8 players" format instead of "3 players"

**New props on RaceCard:**

- `canJoin?: boolean` (default `false`): whether to show the Join button. Computed by the parent based on the user's involvement.

The "Open" badge does not need a prop; it derives from `race.open_registration && race.status === 'setup'`.

## Feature 3: Dashboard "Races to Join" Section

A new section on the dashboard page, positioned after "Active Now" and before "Recent Activity".

**Behavior:**

- Title: "Races to Join" (gold, same style as other section titles)
- Displays joinable races using the same RaceCard component (with `canJoin={true}`)
- Grid layout: 2 columns (same as "Active Now"), 1 column on mobile
- Section hidden entirely if there are no joinable races
- Link "Browse all races" at the bottom, navigating to `/races`

**Data source:** `GET /api/races/joinable`, fetched alongside the existing dashboard data in `Promise.all`.

## API: `GET /api/races/joinable`

New endpoint on the races router. Requires authentication.

**Query:** Selects races where:

- `status = 'setup'`
- `open_registration = true`
- `is_public = true`
- User is NOT the organizer (`organizer_id != user.id`)
- User is NOT a participant (no row in `participants` for this user)
- User is NOT a caster (no row in `casters` for this user)
- Not full: `max_participants IS NULL` OR `participant_count < max_participants` (participant_count computed via subquery or len)

**Response:** `RaceListResponse` (same schema as `GET /api/races`), ordered by `scheduled_at ASC NULLS LAST, created_at DESC`.

**Client:** New function `fetchJoinableRaces()` in `api.ts` calling `GET /api/races/joinable`.

## Component Changes Summary

| Component                | Change                                                                            |
| ------------------------ | --------------------------------------------------------------------------------- |
| `+layout.svelte`         | Fetch joinable count on mount (logged-in only), render pill badge on "Races" link |
| `RaceCard.svelte`        | Add "Open" badge, "Join" outlined button (conditional), "x/max players" format    |
| `dashboard/+page.svelte` | New "Races to Join" section after "Active Now"                                    |
| `api.ts`                 | New `fetchJoinableRaces()` function                                               |
| `api/races.py`           | New `GET /api/races/joinable` endpoint                                            |
| `app.css`                | New `.badge-open` class (green, matching success color)                           |

## Non-Goals

- No real-time updates of the navbar count (refreshed on page navigation via layout mount)
- No client-side join action from the card (always navigates to race detail)
- No changes to the race detail page (join flow there is already complete)
- No filtering/sorting changes on the `/races` page (can be added later)
