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
within one stage), semi seeds that do not cover the ladder from 1 without a
gap (the newcomers' group draws from the ladder positions after the largest
seed used by any semi, so a gap would exclude those positions from every
playoff group at once), a `phase_override` outside the five phases, and a
naive (timezone-less) `announced_at` or stage `date`. `starts_at`, `qualifier_ends_at`
and `ends_at` on the upsert request are rejected the same way when naive.

One invariant worth keeping in mind when editing this schema: any future
tightening of `EventConfig` validation must ship together with a backfill of
already-stored configs. The public event page validates the stored document
on every request, so a document that was valid when saved but fails the new
rules reads as "Event not found" for every viewer until it is fixed. The
repair path stays open: the admin Events tab lists such an event anyway, with
the validation errors under its name (`config_error`) and a phase computed
from the dates alone, and its editor loads the stored document as it is.
Attaching a race to a slot needs the parsed config, so it refuses with a 422
naming the same errors.

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
Daily seeds are races, so they count towards that; solo sessions are not, so
they do not. The format block names daily seeds explicitly, since "races"
alone reads as organised races to a player who mostly runs the daily.

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
viewers. A qualifier race still in setup, which is how it sits between the
announcement and the opening, shows as upcoming on its card with no play
strip whatever its registration state: the opening date while the event is
upcoming, "Not open yet" once it has opened and the race has not been
started.
`closes_at` is the race's
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
3. On the opening day: start each qualifier race as its organizer. Until
   then their cards read as upcoming, since the packs are not out. During the
   week that follows: nothing. To void a broken seed, detach it.
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
- An event whose stored config no longer parses is refused (422, naming the
  validation errors): the slot cannot be checked without it. Detaching still
  works, since it never reads the config.
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
All dates and times render in the viewer's browser timezone, and the instants
still ahead of the viewer name that timezone too ("Wed 30 Sept, 21:00 CEST"):
the take-part steps, the seed cards' opening, the qualified groups with the
`Cut` tile beside them (that block only shows before the cut), and the stage
whose races the bracket block lists. What the viewer can no longer act on
keeps the plain form: the ladder's `Closed` fact, the same deadline read
after it passed, and the phase signal.

The format block keeps its dates to the day, in brass, and closes the playoff
paragraph with the time the evenings start at ("Playoff evenings start at
21:00 in your timezone"). `stageTimes` reads that from the stage dates: one
time when they share it, plus the single evening that falls elsewhere when
exactly one does ("the Final at 20:00"), and nothing when no single evening
stands out against a majority: three or more times, an even split, two
evenings that merely differ, or a lone stage. A season scheduled so that two
evenings fall either side of a daylight saving change, out of four, loses the
line for the viewers that change applies to, and for them only. Only the wall
clock counts, never the zone's name,
so evenings kept at one local time across a daylight saving change still read
as one time. That change is the ordinary case rather than a corner one: the
real season's last evening is the Sunday Europe leaves summer time.

The take-part steps start on the viewer's own state: the Twitch button while
they are signed out, and once they are signed in, a verdigris line with their
name (and their avatar when they have one) instead, so the step reads as done
rather than repeating the instruction.

Practice is pushed where it is cheap to act on, never as a block of its own:
each mode group in the qualifier seeds links to that mode's solo pool
(`training_<mode key>`, and the solo page falls back to its own default when
no such pool exists), step 02 says the same before the seeds are out, and
during the qualifier the note above the seeds names the modes the viewer has
never opened, or sends them to the daily once every seed is spent
(`practiceHint`). All of it reads `my_result`, so it costs no extra request,
and it shows only to a signed-in viewer, since the solo page needs an account.

While the event can still be joined (`upcoming` and `qualifier`), a "What is
SpeedFog?" section opens the page for visitors who have never played: three
concepts beside a silent looping montage of a run, and a link to a longer cut
on YouTube. The media are constants at the top of `EventIntro.svelte` rather
than event config, since they describe SpeedFog and not the event; while unset,
the section shows a still from a run and no link. The loop plays muted and
inline, with a play/pause button for every viewer, and starts paused for a
viewer who prefers reduced motion.

Once the phase
is `finished`, two compact plates under the band crown the final's and the
newcomers' final's winners (the leader of each complete stage), the champion's
larger, with their story: the position they qualified at on the ladder, the
evening's races finished first out of the races expected (a race nobody
finished counts for no one), and their signature weapon, the one carried the
longest over every event race they entered (`signature_weapon` on each stage
result, from the zone histories). An event that ends at `ends_at` with the
final incomplete shows no plate.

### Seeing each state locally

`tools/simulate_event.py <stage>` fills a local database with a whole
simulated season and projects it at the state named by the stage, shifting
every date so that state is the current one: the announcement, the open
qualifier, the cut, and the semi A, newcomers' and open finals both live and
finished. The event must already exist, and its modes and stages must match
the ones the tool hardcodes. It writes fabricated participations onto real
user rows and consumes an available seed for each of the eighteen races it
creates, so it refuses a database that is not on this machine.
`--viewer <twitch username>` gives that runner a seed of every card state.

## Open Graph

Sharing `/events/<slug>` unfurls a card rendered by the server, like race and
daily pages: nginx routes known crawlers to `GET /api/og/event/{slug}/meta`,
whose tags point at `GET /api/og/event/{slug}.png`.

The card follows the phase, on the same computation as the page
(`summarize_event` in `services/og_image.py` reuses `event_service`):

| phase             | body                                                         |
| ----------------- | ------------------------------------------------------------ |
| `upcoming`        | the day the qualifier opens                                  |
| `qualifier`       | every entrant as one row of avatars, then the closing day    |
| `cut`, `playoffs` | the current stage's line-up by name, then the stage and date |
| `finished`        | the winner of the final                                      |

The header carries the phase, the co-brand lockup sits under it with the
partner logo, and the footer holds the entrant count and the event window.
Entrants run in ladder order (best first), capped at 14 with a `+N` chip. A
line-up slot nobody holds yet is a dashed ring labelled with what it waits on:
a seed number for a semi, the source stage for the final. A finished event
whose final never happened falls back to the entrant row.

Stage dates show the day in UTC, no time: an evening slot never lands on a
different day for a European or American viewer, so the card needs no timezone.

The PNG is cached on disk as `event-<slug>-v<template>-<key>.png`, the key
hashing what the card shows (phase, stage, line-up, entrants, counts, the
partner logo URL), so it is
re-rendered when the event moves and served from disk otherwise. The partner
logo is fetched once from `partner_logo_url` (rooted at `base_url` when the
value is site-relative) and cached next to the avatars; a logo that cannot be
fetched is left out rather than replaced by a placeholder.

## API

- `GET /api/events/{slug}`: the page's single payload (`EventDetailResponse`).
- `GET /api/admin/events`, `POST /api/admin/events` (upsert by slug),
  `POST /api/admin/races/{race_id}/event` (`{event_id, slot}` or
  `{event_id: null}`).
- `GET /api/og/event/{slug}/meta` and `GET /api/og/event/{slug}.png`: the
  Open Graph stub and card, for crawlers only.

## See also

- [RACE_LIFECYCLE.md](RACE_LIFECYCLE.md) for the underlying race and
  participant state machines that event races reuse as-is.
- [DAILY_SEED.md](DAILY_SEED.md) for `exclude_from_stats`, the other
  race-level flag events reuse.
