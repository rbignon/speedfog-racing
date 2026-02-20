# Custom DateTimePicker Component

**Date:** 2026-02-20
**Status:** Approved

## Problem

The native `<input type="datetime-local">` is visually inconsistent with the design system and has poor UX (browser-dependent rendering, awkward time input, tiny spinners).

## Solution

Custom `DateTimePicker.svelte` component with:

- **Calendar popup** for date selection (month grid, prev/next navigation)
- **Native `<select>` dropdown** for time selection (30-min slots, 48 options)
- **Zero dependencies** — pure Svelte 5, uses existing CSS custom properties

## Component API

```svelte
<DateTimePicker
  value={scheduledAt}        // ISO 8601 string or ''
  onchange={handleChange}    // (iso: string) => void
  min={new Date()}           // earliest selectable date/time (optional)
  disabled={false}
  placeholder="Pick a date"
/>
```

- `value`: ISO UTC string or empty. Component stores/emits UTC only.
- `onchange`: fires on date or time change with resulting ISO string.
- `min`: `Date` object. Past days grayed out; past time slots hidden when selected day = min day.

## Layout

```
┌──────────────────────┐  ┌──────────┐
│ icon  Feb 20, 2026   │  │ 18:00  ▼ │
└──────────────────────┘  └──────────┘
         ↓ click
┌──────────────────────────┐
│  ❮  February 2026  ❯    │
│ Mo Tu We Th Fr Sa Su     │
│                    1     │
│  2  3  4  5  6  7  8     │
│  ...                     │
└──────────────────────────┘
```

- **Date button**: styled as input, shows formatted date via `Intl.DateTimeFormat`. Toggles calendar popup.
- **Time select**: native `<select>`, visible only when a date is selected. 30-min slots (00:00–23:30).
- **Empty state**: only date button with placeholder, no time select.

## Calendar Popup

- Positioned `absolute` below the date button
- Header: `❮` prev month, `Month Year`, `❯` next month
- 7-column grid (Mo–Su), weeks as rows
- Selected day: `--color-purple` background, white text
- Days before `min`: grayed out, not clickable
- Today: subtle `--color-border` border for reference
- Click day → close popup, update date. Default time `18:00` if no time set yet.
- Click outside or `Escape` → close popup

## Time Select Constraints

- If selected date = min day, filter out slots before min time
- If current slot becomes invalid after date change, snap to next valid slot

## Timezone Handling

- Display: browser local timezone via `Intl.DateTimeFormat` (default = browser tz)
- Small gray label below component shows detected timezone (e.g., "Europe/Paris") via `Intl.DateTimeFormat().resolvedOptions().timeZone`
- Internal conversion: user picks "Feb 20, 18:00" in Europe/Paris → component emits `2026-02-20T17:00:00Z`
- Consumers only deal with UTC ISO strings

## Integration

### `race/new/+page.svelte`

- Replace `<input type="datetime-local">` with `<DateTimePicker>`
- `scheduledAt` stays as ISO string (or `''`), no change to `handleSubmit`
- Remove `input[type='datetime-local']` CSS rules
- Pass `min={new Date()}`

### `race/[id]/+page.svelte` (sidebar schedule edit)

- Replace `<input type="datetime-local">` in `editingSchedule` block
- `scheduleInput` becomes ISO UTC string directly
- Simplify `startEditSchedule()`: pass `initialRace.scheduled_at` directly (already ISO), no manual `getTimezoneOffset` conversion
- Simplify `saveSchedule()`: `scheduleInput` is already ISO, no `new Date(...).toISOString()` needed

### No server changes

Server already receives ISO UTC strings.

## File

Single new file: `web/src/lib/components/DateTimePicker.svelte`
