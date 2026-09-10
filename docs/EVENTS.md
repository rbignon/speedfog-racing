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

| field            | meaning                                                                 |
| ---------------- | ----------------------------------------------------------------------- |
| `modes`          | `[{key, label}]`, keys are pool names, one ladder column each           |
| `seeds_per_mode` | seeds per mode in the qualifier (default 2)                             |
| `stages`         | ordered playoff stages, see below                                       |
| `rules`          | qualifier rules, shown next to the Take part steps (max 300 chars each) |
| `playoff_rules`  | playoff rules, shown next to the bracket from the cut on (same cap)     |
| `facts`          | optional `[{title, lines}]` tiles for the format block (see below)      |
| `phase_override` | force a phase (`upcoming`, `qualifier`, `cut`, `playoffs`, `finished`)  |
| `announced_at`   | first timeline stop; defaults to `starts_at` minus 7 days               |

A stage: `key`, `label`, `kind` (`semi`, `newcomers`, `final`), `date`,
`races` (per evening), `modes` (display labels, not pool keys: one chip per
race in the bracket boxes and qualified groups, linking to the race page once
a race is attached, and the name of a race placeholder), plus `seeds` (ladder positions) for a semi, `size` for the
newcomers' final, `from` and `advance` for the final. Stage dates ascend;
`qualifier_ends_at` is at or before the first stage; `ends_at` is after the
last.

Validation also rejects: seed numbers reused across `semi` stages (not just
within one stage), a `phase_override` outside the five phases, and a naive
(timezone-less) `announced_at` or stage `date`. `starts_at`, `qualifier_ends_at`
and `ends_at` on the upsert request are rejected the same way when naive.

Two invariants worth keeping in mind when editing this schema:

- Any future tightening of `EventConfig` validation must ship together with a
  backfill of already-stored configs: the public event page validates the
  stored document on every request, so a document that was valid when saved
  but fails the new rules would break the page for every viewer until it is
  fixed or backfilled.
- A semi stage's `seeds` must cover ladder positions contiguously from 1
  (across all semi stages combined). The newcomers' group draws from the
  ladder positions after the largest seed used by any semi, so a gap in the
  seed numbering silently excludes those positions from both the semis and
  the newcomers' group.

### Facts

The format block shows a grid of small tiles, one title over one to four
lines each. Without `facts` the page derives four of them from the config
(seed and mode counts, the mode labels, stage and race counts, the newcomers'
final day). Setting `facts` (up to 8 tiles, titles up to 40 characters,
lines up to 60) replaces that grid with free text, so an event can say
"4 Sundays" or name a seasonal pool; an empty list behaves like an unset
field. Fact lines are plain text: a date typed there is not converted to the
viewer's timezone, so keep dates to the day.

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

The admin events list computes `phase` without grouping the races by stage, so
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
evenings sum the points of their races (100 / 75 / 50 / 25 with four runners);
a running race scores provisionally, so the bracket shows a stage's points in
brass until the stage is complete.

## Qualifier races

Each qualifier race in `qualifier_races` carries `my_result` for the
signed-in viewer: `not_played` (never joined), `joined` (registered or ready,
the pack still to run), `playing`, or `done` (always with `igt_ms`; also
`rank`, `points` and `provisional` once the run has a score, i.e. at least
two zone entries). `finished` is present on every `my_result` and is false
for an abandoned run, which the page labels DNF. On the seed card a scored
DNF takes the finished colour (verdigris route line and result facts, the
points in brass while provisional), since the run holds a rank and points; a DNF without a score shows the spent grey
line, since the seed can be neither scored nor replayed. `null` for anonymous
viewers. `closes_at` is the race's
`started_at + race_duration_minutes`, the same instant as the race's own
`race_ends_at`.

## Running an event (admin)

1. `/admin`, Events tab: create the event from the template, adjust dates,
   modes and stages, save. Mode keys must be pool names. A rejected save
   shows the server's validation errors next to the JSON editor, each
   prefixed with its field path. A save is also rejected when the new config
   would orphan a race already attached to a slot it no longer has room for
   (a removed or renamed mode or stage, or a lowered `seeds_per_mode`): the
   error names the orphaned slots, and nothing is stored until the races are
   detached from the Races tab.
2. Before the qualifier: create the qualifier races with the normal form,
   private, registration by link, late join equal to the duration (10080
   minutes for a week), then attach each to `qualifier:<mode>:<n>` from the
   Races tab. Attaching sets `exclude_from_stats` and hides the race from the
   public listings.
3. During the qualifier: nothing. To void a broken seed, detach it.
4. Before each playoff evening: create the stage's public races (four slots, a
   duration cap), add the qualified runners and the casters, attach to
   `<stage>:<n>`. Name them "Semi B - Race 1 - Standard", hyphenated like
   daily races: the race cards beside the bracket display the race name
   without the stage label the section already carries ("Race 1 -
   Standard"), and drop the players / mode / organizer foot row and the
   viewer's role mark, since the bracket beside them lists the field and
   each stage's date and modes (an organizer or caster finds their role on
   the race page). A slot with no race yet shows a placeholder named the
   same way, carrying the stage's expected runners as an avatar stack. Start
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

`exclude_from_stats` is read only by the community-wide trait-score recompute
(`stats_service.recalculate_all_stats`); it has no effect on the event's own
ladder, on the race listings, or on the event page.

## The event page

`/events/[slug]` polls `GET /api/events/{slug}` every 60 seconds while a
stage race is RUNNING, and every 5 minutes on a playoff day (a stage dated
within 12 hours of now) so an open page sees the evening's race go live;
during the qualifier it only refreshes on page reload.
All dates and times render in the viewer's browser timezone.

## API

- `GET /api/events/{slug}`: the page's single payload (`EventDetailResponse`).
- `GET /api/admin/events`, `POST /api/admin/events` (upsert by slug),
  `POST /api/admin/races/{race_id}/event` (`{event_id, slot}` or
  `{event_id: null}`).

## See also

- [RACE_LIFECYCLE.md](RACE_LIFECYCLE.md) for the underlying race and
  participant state machines that event races reuse as-is.
- [DAILY_SEED.md](DAILY_SEED.md) for `exclude_from_stats`, the other
  race-level flag events reuse.
