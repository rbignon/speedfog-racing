# User Profile Page — Design

**Date:** 2026-02-16
**Status:** Approved

## Goal

Public user profile page showing a player's activity history (races, training, organizing, casting) with aggregated stats. Usernames become clickable links throughout the app.

## URL

`/user/{twitch_username}` — uses Twitch username for readable, shareable URLs.

## API

### `GET /api/users/{username}` — Profile + Stats (public)

Response:

```json
{
  "id": "uuid",
  "twitch_username": "roger42",
  "twitch_display_name": "Roger42",
  "twitch_avatar_url": "https://...",
  "role": "organizer",
  "created_at": "2026-01-15T...",
  "stats": {
    "race_count": 12,
    "training_count": 8,
    "podium_count": 3,
    "first_place_count": 1,
    "organized_count": 5,
    "casted_count": 2
  }
}
```

Stats computed via SQL subqueries (COUNT with filters). Placement for podium/first_place derived from IGT ranking among FINISHED participants per race.

### `GET /api/users/{username}/activity?offset=0&limit=20` — Timeline (public)

Returns a chronologically sorted (newest first) list of activity entries with discriminated `type` field.

```json
{
  "items": [
    {
      "type": "race_participant",
      "race_id": "uuid",
      "race_name": "FogRando S3 Race 7",
      "date": "2026-02-14T...",
      "status": "finished",
      "placement": 2,
      "total_participants": 6,
      "igt_ms": 3845000,
      "death_count": 12
    },
    {
      "type": "race_organizer",
      "race_id": "uuid",
      "race_name": "FogRando S3 Race 7",
      "date": "2026-02-14T...",
      "participant_count": 6,
      "status": "finished"
    },
    {
      "type": "race_caster",
      "race_id": "uuid",
      "race_name": "FogRando S3 Race 5",
      "date": "2026-02-10T..."
    },
    {
      "type": "training",
      "session_id": "uuid",
      "pool_name": "standard",
      "date": "2026-02-08T...",
      "status": "finished",
      "igt_ms": 2150000,
      "death_count": 5
    }
  ],
  "total": 27,
  "has_more": true
}
```

Server implementation: 4 separate queries (participant, organizer, caster, training), merge + sort in Python, then slice for pagination. Volumes are small (tens of entries per user).

## Frontend

### Profile Page (`/user/[username]/+page.svelte`)

**Header:**

- Large avatar (~64px) + display name + role badge (if organizer/admin)
- "Joined Jan 2026" date

**Stats grid:**

- 6 counters in 2-3 columns: Races, Trainings, Podiums, 1st Places, Organized, Casted
- Compact card style

**Timeline:**

- Vertically stacked cards, newest first
- Card variants by type:
  - **Race (participant):** race name (link), placement ("2nd / 6"), IGT, deaths, status. Podium accent colors (gold/silver/bronze).
  - **Race (organizer):** race name (link), "Organized" badge, participant count, status.
  - **Race (caster):** race name (link), "Casted" badge.
  - **Training:** pool name, IGT, deaths, status. Link to `/training/{id}`.
- Discrete type badge (icon + label) on each card
- "Load more" button at bottom (offset/limit pagination)
- No filters for MVP

### `UserLink.svelte` Component

Reusable component: takes user info (username, display_name, avatar_url optional), renders a styled `<a href="/user/{username}">` with optional inline avatar.

Deployed on:

- Admin page (user table)
- Race detail (leaderboard, casters, organizer)
- Homepage (organizer in race cards)
- Training detail (player name in header)

### Training Detail Update

`/training/[id]` already receives `user` data from the API. Add `UserLink` in the session header to show the player's name — visible to anonymous visitors.

## Out of Scope

- Activity filters (by type) — add later if needed
- User search page
- Private profile settings
