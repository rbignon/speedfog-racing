# Dashboard Onboarding

## Problem

When a new user logs in for the first time, the dashboard shows:

- Four stat counters all at zero (Races, Solo, Organized, Casted)
- "No active sessions" empty state with generic buttons
- No clear direction toward a first meaningful action

The typical new user comes from Discord/Twitch out of curiosity and may not be familiar with the Fog Gate Randomizer. The primary friction is the perception that "randomizer = complex setup", when in reality SpeedFog requires only downloading a zip and launching a bat file.

## Goal

Guide new users to their first solo run as quickly as possible, while reassuring them that setup is trivial.

## Design

### Welcome card (new users only)

A contextual card displayed at the top of the dashboard when the user has zero activity (`race_count + training_count == 0`). It replaces the stats counters section (which would all show zero).

**Content:**

- Title: "Get started"
- Subtitle: "Play your first seed in minutes. No setup, no configuration."
- Three visual steps with icons:
  1. "Start a solo" / "Pick a seed pool and generate your run"
  2. "Download" / "Get the seed pack, a single zip file"
  3. "Run and play" / "Launch the bat file, done"
- Primary CTA: "Play Solo" button (links to `/training`)
- Secondary link: "How it works" (links to `/help`)
- Dismiss link: "Dismiss" (stores dismissal in localStorage)

**Visibility rules:**

- Shown when `profile.stats.race_count + profile.stats.training_count == 0` AND not dismissed via localStorage
- Disappears automatically once the user has any activity (solo or race)
- Can be manually dismissed (localStorage key, same pattern as the existing settings banner)
- When visible, the stats counters section is hidden (all zeros are noise)

### Active Now empty state

The "Active Now" section is hidden entirely when there are no active sessions (both for new and returning users). The navbar already provides direct access to "Solo" and "Races", so repeating those buttons in an empty state adds no value.

### Section ordering

The dashboard sections are reordered for better information hierarchy:

1. Settings banner (existing, dismissible, unchanged)
2. Welcome card (new users) OR Stats counters (returning users)
3. Active Now (only when non-empty)
4. Races to Join (only when available)
5. Pool Stats (only when non-empty)
6. Recent Activity (only when non-empty)

Previously, Pool Stats sat between Stats and Active Now, pushing actionable content below the fold when pool stats were large. The new order prioritizes actionable content (active sessions, joinable races) over reference data (pool stats, activity history).

## Scope

- Frontend only, no backend changes needed
- Single file change: `web/src/routes/dashboard/+page.svelte`
- No new components (the welcome card is simple enough to be inline)
- localStorage key for dismiss (same pattern as existing `speedfog_settings_banner_dismissed`)

## Out of scope

- Changes to the homepage (`+page.svelte`), about page, or help page
- New user role detection or server-side onboarding state
- Multi-step onboarding wizard or tooltips
- Changes to the navbar
