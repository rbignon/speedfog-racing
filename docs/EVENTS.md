# Events

A co-branded tournament run on the platform: one week of qualifying on dedicated
week-long seeds, then playoff evenings, all on one page, `/events/[slug]`. The
first instance is SpeedFog x Ignite Season One (qualifier 23 to 30 September
2026, playoffs on Sundays 4, 11, 18 and 25 October).

## Model

`events` holds the dates and a JSON `config`; races attach through
`races.event_id` and `races.event_slot` (`qualifier:<mode>:<n>` or
`<stage>:<n>`, unique per event). Nothing else is stored: the ladder, the
qualified groups, the playoff results and the phase are computed on each
request by `services/event_service.py`.

### Config

| field            | meaning                                                                |
| ---------------- | ---------------------------------------------------------------------- |
| `modes`          | `[{key, label}]`, keys are pool names, one ladder column each          |
| `seeds_per_mode` | seeds per mode in the qualifier (default 2)                            |
| `stages`         | ordered playoff stages, see below                                      |
| `rules`          | strings shown in the rules card (max 300 characters each)              |
| `phase_override` | force a phase (`upcoming`, `qualifier`, `cut`, `playoffs`, `finished`) |
| `announced_at`   | first timeline stop; defaults to `starts_at` minus 7 days              |

A stage: `key`, `label`, `kind` (`semi`, `newcomers`, `final`), `date`,
`races` (per evening), `modes` (display labels shown under the bracket, not
pool keys), plus `seeds` (ladder positions) for a semi, `size` for the
newcomers' final, `from` and `advance` for the final. Stage dates ascend;
`qualifier_ends_at` is at or before the first stage; `ends_at` is after the
last.

Validation also rejects: seed numbers reused across `semi` stages (not just
within one stage), a `phase_override` outside the five phases, and a naive
(timezone-less) `announced_at` or stage `date`.

### Timeline

`GET /api/events/{slug}` returns the timeline as an ordered list of stops:
`announce`, `open` (at `starts_at`), `cut` (at `qualifier_ends_at`), then one
`stage:<stage key>` per configured stage, in stage order. `announce` uses
`announced_at` when the config sets it, otherwise `starts_at` minus 7 days.

## Phases

| phase       | when                                                 |
| ----------- | ---------------------------------------------------- |
| `upcoming`  | before `starts_at`                                   |
| `qualifier` | until `qualifier_ends_at`                            |
| `cut`       | until the first stage date                           |
| `playoffs`  | until `ends_at`, or until the last stage is complete |
| `finished`  | after                                                |

The ladder is provisional until every attached qualifier race is FINISHED. A
stage is complete when it has all its races attached and FINISHED; its
advancing runners (the final's `advance`) then fill the final automatically.

The admin events list computes `phase` without loading the event's races, so
it always treats the last stage as not yet complete. This only matters
between the last stage finishing and `ends_at`: in that window the admin list
still shows `playoffs`, while the public event page (which loads the stage
races) already shows `finished`.

## Scoring

Each event race scores with the daily formula (`compute_daily_points`): 100 to
first, proportional down the field, unfinished runs ranked by depth reached
then time, floor of 1, over runs with at least two zone entries. Ladder: best
seed per mode, summed over the modes; a score in every mode is required to be
ranked; ties on the summed in-game time of the counted seeds. Newcomers have
fewer than `newcomer_threshold` finished races started before `starts_at`.

A semi stage's `seeds` index into the sorted ladder position by position
(seed 1 is the top entry, seed 2 the next, and so on), not by each entry's own
displayed rank. Tied runners occupy consecutive positions sharing the same
rank, so a seed number can resolve to a runner whose displayed ladder rank is
lower than the seed itself (e.g. a three-way tie for rank 1 means seed 3 also
holds a rank-1 runner). A runner with no scoring qualifier run (fewer than two
zone entries on every attached seed) never enters the ladder at all: the
ladder's `entered` count is the number of runners with at least one scoring
run, not the number who joined a qualifier race.

Qualified groups map each semi's `seeds` to ladder positions; the newcomers'
group takes the first ranked newcomers positioned after the last seed. Playoff
evenings sum the points of their races (100 / 75 / 50 / 25 with four runners).

## Qualifier races

Each qualifier race in `qualifier_races` carries `my_result` for the
signed-in viewer: `not_played` (never joined), `joined` (registered or ready,
the pack still to run), `playing`, or `done` (with `rank`, `igt_ms`, `points`
and `provisional` once a score exists); `null` for anonymous viewers.
`closes_at` is the race's `started_at + race_duration_minutes`, the same
instant as the race's own `race_ends_at`.

## Running an event (admin)

1. `/admin`, Events tab: create the event from the template, adjust dates,
   modes and stages, save. Mode keys must be pool names. A rejected save
   shows the server's validation errors next to the JSON editor, each
   prefixed with its field path.
2. Before the qualifier: create the qualifier races with the normal form,
   private, registration by link, late join equal to the duration (10080
   minutes for a week), then attach each to `qualifier:<mode>:<n>` from the
   Races tab. Attaching sets `exclude_from_stats` and hides the race from the
   public listings.
3. During the qualifier: nothing. To void a broken seed, detach it.
4. Before each playoff evening: create the stage's public races (four slots, a
   duration cap), add the qualified runners and the casters, attach to
   `<stage>:<n>`. Name them as the page shows them, "Semi B · Race 1 ·
   Standard": the race cards under the bracket display the race name. Start
   each race as its organizer on the evening.

No manual transition exists: the page follows the dates and the race states.
`phase_override` is the escape hatch for schedule accidents.

### Attaching a race to a slot

`POST /api/admin/races/{race_id}/event` with `{event_id, slot}` attaches a
race; `{event_id: null}` detaches it, clearing both `event_id` and
`event_slot` and leaving `exclude_from_stats` unchanged. Attaching validates:

- The slot must exist for the event's config (a known mode and seed index for
  a `qualifier:<mode>:<n>` slot, a known stage and race index for a
  `<stage>:<n>` slot).
- A `qualifier:<mode>:<n>` slot requires the race's seed pool to equal the
  mode key, and `late_join_window_minutes` and `race_duration_minutes` both
  set and equal; attaching then sets `exclude_from_stats` on the race.
- A stage slot requires `max_participants` to be null or at least the stage's
  field size: the number of `seeds` for a semi, `size` for a newcomers stage,
  `advance` times the number of `from` stages for a final.
- A Daily Seed race is refused.
- An occupied slot is a 409, including the race between two admins attaching
  to the same slot at once (caught by the unique constraint on
  `(event_id, event_slot)`).

## The event page

`/events/[slug]` polls `GET /api/events/{slug}` every 60 seconds only while a
stage race is RUNNING; during the qualifier it only refreshes on page reload.
All dates and times render in the viewer's browser timezone.

## API

- `GET /api/events/{slug}`: the page's single payload (`EventDetailResponse`).
- `GET /api/admin/events`, `POST /api/admin/events` (upsert by slug),
  `POST /api/admin/races/{race_id}/event` (`{event_id, slot}` or
  `{event_id: null}`).
