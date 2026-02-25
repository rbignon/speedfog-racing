# Add to Calendar Button

## Overview

Add a calendar icon button next to the Share button on the race detail page header. Clicking it opens a dropdown with options to add the race to Google Calendar, Apple Calendar, or Outlook.

## Visibility

- Only shown when `race.scheduled_at` is defined
- Positioned immediately next to the existing ShareButtons component in the race header

## UI

- Icon button: 32x32px calendar SVG icon, same style as the share button (neutral border, gold on hover)
- Dropdown on click:
  - `background: var(--color-surface-elevated)`, `border: 1px solid var(--color-border)`, `border-radius: var(--radius-lg)`, shadow
  - Three options: Google Calendar, Apple Calendar, Outlook
  - Each option: provider icon + label text
  - Close on click outside

## Calendar Event Data

- **Title**: `SpeedFog Race #<seed_number>` (or `SpeedFog Race` if no seed assigned)
- **Start**: `scheduled_at`
- **Duration**: 1 hour (default, races have no predefined duration)
- **URL**: link to the race page
- **Description**: link to the race page

## Implementation

- New component: `web/src/lib/components/AddToCalendar.svelte`
- Google Calendar: opens new tab with URL `https://calendar.google.com/calendar/render?action=TEMPLATE&text=...&dates=...&details=...`
- Apple Calendar / Outlook: generates `.ics` file client-side as a Blob, triggers download via `<a download="race.ics">`
- No server-side changes needed

## .ics Format

```
BEGIN:VCALENDAR
VERSION:2.0
PRODID:-//SpeedFog Racing//EN
BEGIN:VEVENT
DTSTART:<scheduled_at in UTC format YYYYMMDDTHHMMSSZ>
DTEND:<scheduled_at + 1h>
SUMMARY:<title>
DESCRIPTION:<race URL>
URL:<race URL>
END:VEVENT
END:VCALENDAR
```
