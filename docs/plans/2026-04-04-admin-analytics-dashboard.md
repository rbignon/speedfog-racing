# Admin Analytics Dashboard

Add analytics visualizations to the admin Stats tab: KPI summary cards,
weekly activity charts, day/hour heatmaps, and timezone distribution.

## Scope

### 1. KPI Summary Cards (top row)

Four cards displaying headline metrics:

| Card             | Main value                                  | Subtitle                                                         |
| ---------------- | ------------------------------------------- | ---------------------------------------------------------------- |
| Total Users      | `count(users)`                              | `+N this month` (users created in current calendar month)        |
| Active (30d)     | `count(users where last_seen >= now - 30d)` | `X% of total`                                                    |
| Races (finished) | `count(races where status = finished)`      | `avg N.N players` (mean participant count across finished races) |
| Solo Sessions    | `count(training_sessions)`                  | `X% finished` (finished / (finished + abandoned))                |

### 2. Weekly Bar Charts (Chart.js)

Four bar charts showing the last 12 weeks of data. Each chart is a
`Chart.js` bar chart rendered in a `<canvas>` element.

#### New Users per Week

- Y: count of users with `created_at` in that ISO week
- Color: purple (`#8b5cf6`)

#### Races & Solo per Week

- Stacked bars: races (gold `#c8a44e`) + solo sessions (purple `#8b5cf6`)
- Races: count of races with `started_at` in that week (status = running or finished)
- Solo: count of training sessions with `created_at` in that week

#### Solo Completion Rate per Week

- Stacked bars: finished (green `#22c55e`) + abandoned (red `#ef4444`)
- Only counts sessions with a terminal status (finished or abandoned)

#### Avg Participants per Race per Week

- Y: mean number of participants for races started that week
- Color: gold (`#c8a44e`)

Week labels: `"W{n}"` format (ISO week number). X-axis shows the 12 most
recent weeks. Weeks with no data show as 0.

### 3. Activity Heatmaps (side by side)

Two CSS grid heatmaps, rendered without Chart.js (pure HTML/CSS like the
existing DAG components):

#### Race Players (left, gold)

- Grid: 7 columns (Mon-Sun) x 8 rows (10h, 12h, 14h, 16h, 18h, 20h, 22h, 00h)
- Cell value: sum of participant counts for races started in that day/hour slot
- Source timestamp: `Race.started_at`
- Color: `rgba(200, 164, 78, opacity)` where opacity scales linearly from 0 to
  the max cell value

#### Solo (right, purple)

- Same grid layout
- Cell value: count of training sessions started in that day/hour slot
- Source timestamp: `TrainingSession.created_at`
- Color: `rgba(139, 92, 246, opacity)` with same linear scaling

Each heatmap has its own independent color scale and a legend strip
showing the gradient from 0 to max.

Hour slots use 2-hour buckets: a session at 11:30 falls in the 10h bucket,
a session at 14:15 falls in the 14h bucket.

### 4. Timezone Distribution (Chart.js)

Vertical bar chart showing user count per IANA timezone, ordered west to
east by UTC offset.

- X-axis: timezone labels (e.g., "America/Los_Angeles") with UTC offset
  subtitle (e.g., "UTC-8")
- Y-axis: user count
- Color: purple (`#8b5cf6`)
- Only timezones with at least 1 user are shown
- Users with `timezone = NULL` are excluded (not shown)

### 5. Recalculate Stats Button

Existing button preserved at the bottom of the tab, unchanged.

## Data Collection: User Timezone

New field on the `User` model:

```python
timezone: Mapped[str | None] = mapped_column(String(50), nullable=True)
```

**Collection mechanism:** the frontend reads `Intl.DateTimeFormat().resolvedOptions().timeZone`
and sends it as a query parameter or header on the `GET /auth/me` call.
The server updates `User.timezone` on each `/auth/me` call (alongside
the existing `last_seen` update). This ensures the timezone stays current
if a user travels or relocates.

No migration backfill needed; users with `timezone = NULL` are simply
excluded from the timezone chart until their next visit.

## API

Single new endpoint: `GET /api/admin/analytics`

Requires admin role. Returns all dashboard data in one response:

```json
{
  "kpis": {
    "total_users": 47,
    "new_users_this_month": 5,
    "active_users_30d": 18,
    "active_users_pct": 38.3,
    "total_races_finished": 32,
    "avg_participants": 4.1,
    "total_solo": 124,
    "solo_completion_pct": 68.5
  },
  "weekly": {
    "weeks": [
      "W5",
      "W6",
      "W7",
      "W8",
      "W9",
      "W10",
      "W11",
      "W12",
      "W13",
      "W14",
      "W15",
      "W16"
    ],
    "new_users": [1, 2, 3, 1, 4, 2, 5, 3, 2, 6, 3, 5],
    "races": [0, 1, 1, 2, 0, 1, 2, 1, 3, 1, 2, 1],
    "solo": [3, 5, 4, 8, 6, 7, 10, 9, 12, 8, 11, 9],
    "solo_finished": [2, 3, 3, 5, 4, 5, 7, 6, 9, 5, 8, 6],
    "solo_abandoned": [1, 2, 1, 3, 2, 2, 3, 3, 3, 3, 3, 3],
    "avg_participants": [0, 3.0, 4.0, 3.5, 0, 5.0, 4.0, 3.0, 4.3, 4.0, 4.5, 3.0]
  },
  "heatmaps": {
    "race_players": [
      [0, 0, 0, 0, 0, 3, 2],
      [0, 0, 0, 0, 0, 5, 4],
      "...8 rows of 7 values"
    ],
    "solo": [[1, 0, 1, 0, 2, 4, 5], "...8 rows of 7 values"]
  },
  "timezones": [
    { "timezone": "America/Los_Angeles", "offset_minutes": -480, "count": 7 },
    { "timezone": "America/New_York", "offset_minutes": -300, "count": 12 },
    { "timezone": "Europe/London", "offset_minutes": 0, "count": 5 },
    { "timezone": "Europe/Paris", "offset_minutes": 60, "count": 18 },
    { "timezone": "Asia/Tokyo", "offset_minutes": 540, "count": 3 }
  ]
}
```

Heatmap rows are ordered: 10h, 12h, 14h, 16h, 18h, 20h, 22h, 00h.
Heatmap columns are ordered: Mon, Tue, Wed, Thu, Fri, Sat, Sun.

The `offset_minutes` field is computed server-side from the IANA timezone
name using Python's `zoneinfo` module (current UTC offset at query time).
This is used by the frontend to sort bars west-to-east.

## Frontend

### Dependencies

Add `chart.js` to `web/package.json`:

```bash
npm install chart.js
```

### Component Structure

The Stats tab content in `web/src/routes/admin/+page.svelte` will be
extracted into inline sections (not separate components, since this is a
single admin page):

1. KPI cards: simple HTML grid, no Chart.js
2. Weekly charts: four `<canvas>` elements, each initialized with Chart.js
3. Heatmaps: CSS grid with inline background-color opacity
4. Timezone chart: one `<canvas>` element with Chart.js
5. Recalculate button: existing markup, unchanged

Chart.js instances are created in an `$effect` that runs after data loads.
Charts are destroyed and recreated when data changes (standard Chart.js
lifecycle in Svelte).

### Colors

Use existing CSS custom properties from the graphic charter:

- Gold: `#c8a44e` (races)
- Purple: `#8b5cf6` (solo / users)
- Green: `#22c55e` (finished)
- Red: `#ef4444` (abandoned)
- Surface: `var(--color-surface)` for card backgrounds

## Server Implementation

All analytics queries live in a new service file
`server/speedfog_racing/services/analytics_service.py` with a single
public function:

```python
async def compute_analytics(db: AsyncSession) -> dict
```

This function runs the SQL queries for KPIs, weekly buckets, heatmaps,
and timezone distribution, and returns the structured dict matching the
API response schema.

The endpoint in `api/admin.py` calls this service and returns the result.

No caching; the queries hit the database directly on each request. The
dataset is small (dozens of users, hundreds of races/sessions) and this
is an admin-only page with low traffic.

## Testing

- **Server unit test**: test `compute_analytics` with fixture data covering
  multiple weeks, timezones, and edge cases (empty weeks, NULL timezones)
- **API test**: test `GET /api/admin/analytics` returns 200 for admin,
  403 for non-admin
- **Timezone collection test**: test that `GET /auth/me` with timezone
  parameter updates `User.timezone`
