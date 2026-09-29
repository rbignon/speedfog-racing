# Events

A co-branded tournament run on the platform: one week of qualifying on dedicated
week-long seeds, then playoff evenings, all on one page, `/events/[slug]`. The
first instance is SpeedFog x Ignite Season One (qualifier 23 September to 8
October 2026; quarters and semis scheduled with their players, the final on
25 October).

## Model

`events` holds the dates and a JSON `config`; races attach through
`races.event_id` and `races.event_slot` (`qualifier:<mode>:<n>` or
`<stage>:<n>`, unique per event). `event_signups` holds who said they are in
(one row per event and user, kept in signup order). Nothing else is stored:
the ladder, the qualified groups, the playoff results and the phase are
computed on each request by `services/event_service.py`.

### Config

| field                    | meaning                                                                            |
| ------------------------ | ---------------------------------------------------------------------------------- |
| `modes`                  | `[{key, label}]`, keys are pool names, one ladder column each                      |
| `seeds_per_mode`         | seeds per mode in the qualifier (default 2)                                        |
| `stages`                 | ordered playoff stages, see below                                                  |
| `showcases`              | evenings outside the bracket, for the cast scenes (see Showcases)                  |
| `rules`                  | qualifier rules, shown next to the Take part steps (max 300 chars each)            |
| `playoff_rules`          | playoff rules, shown next to the bracket from the cut on (same cap)                |
| `playoff_points`         | points per finishing rank in a playoff race (default 100/70/40/20)                 |
| `playoff_cutoff_minutes` | minutes the field has once a playoff race's first runner finishes (default 10)     |
| `facts`                  | optional `[{title, lines}]` tiles for the format block (see below)                 |
| `phase_override`         | force a phase (`upcoming`, `qualifier`, `cut`, `playoffs`, `finished`)             |
| `announced_at`           | the announcement: first timeline stop and newcomer cut (see Timeline)              |
| `withdrawn`              | qualified runners who gave up their place, Twitch usernames (see Qualified groups) |

A stage: `key`, `label`, `kind` (`round`, `quarter`, `semi`, `newcomers`,
`final`), `date` (optional: see below), `races` (per evening), `modes`
(display labels, not pool keys: one chip per race in the bracket boxes and
qualified groups, linking to the race page once a race is attached, and the
name of a race placeholder), and where its runners come from: `seeds`
(ladder positions) or `from` (earlier stages it takes runners from), or
`size` for the newcomers' final. `advance` sits on the stage that sends
runners on: how many of its runners go to the stage naming it in `from` (the
top 2 of each group of a round, of each quarter, of each semi). The kind
only matters for display, except `final` (its winner is the champion) and
`newcomers` (its own draw). `round` is a seeded round played before the
quarters; the format paragraph names it after its seats ("round of 32").

A stage without a `date` is scheduled with its players: its date is the
earliest of its attached races' `scheduled_at` (or `started_at` for a private
race, which needs no schedule), and it has none until an attached race is
scheduled (or has started).
The detail returns that effective date on each stage, with `date_fixed` true
when the config sets it, and `from` for the connectors. The dated stages
ascend; `qualifier_ends_at` is at or before the first dated stage; `ends_at`
is after the last.

Validation also rejects: a stage with both or neither of `seeds` and `from`
(a newcomers stage has `size` and neither), a `from` naming a stage placed
later in the list, an unknown stage or the newcomers stage (list order is
bracket order), a stage feeding more than one stage, `advance` on a stage
nothing takes from or missing on one something does, an `advance` larger
than the field it comes from, a second final or newcomers stage, seed numbers
reused across stages (not just within one), seeds that do not cover the
ladder from 1 without a gap (the newcomers' group draws from the ladder
positions after the largest seed used by any stage, so a gap would exclude
those positions from every playoff group at once), a `phase_override`
outside the five phases, a `newcomers` stage without `announced_at`, a blank
or repeated `withdrawn` name (case-insensitive), and a naive (timezone-less)
`announced_at` or stage `date`. `starts_at`, `qualifier_ends_at` and
`ends_at` on the upsert request are rejected the same way when naive, and so
is an `announced_at` at or after `starts_at`: the qualifier's own runs would
otherwise count towards the newcomer cut. The admin upsert also refuses a
`withdrawn` name that matches no user's Twitch username.

One invariant worth keeping in mind when editing this schema: any future
tightening of `EventConfig` validation must ship together with a backfill of
already-stored configs. The public event page validates the stored document
on every request, so a document that was valid when saved but fails the new
rules reads as "Event not found" for every viewer until it is fixed. The
repair path stays open: the admin Events tab lists such an event anyway, with
the validation errors under its name (`config_error`) and a phase computed
from the dates alone, and its editor loads the stored document as it is.
Attaching a race to a slot needs the parsed config, so it refuses with a 422
naming the same errors. Moving `advance` from the final onto the stages that
feed it was such a change: its migration (`4f7c2a9d1e6b`) rewrites the stored
documents, and runs again harmlessly on one already moved.

### Showcases

A showcase is an evening outside the bracket, a match between runners picked
by hand, that the talk cast scene can still score (see
[CAST_OVERLAYS.md](CAST_OVERLAYS.md)). It takes a `key`, a `label`, `races`,
`modes` and an optional `date`, with the same meaning as a stage's, and none
of `kind`, `seeds`, `from`, `advance` or `size`: its field is whoever races
it, the participants of its attached races by username. Its races attach to
`<key>:<n>` like a stage's, so validation rejects a key used by both a stage
and a showcase. They score as a stage's do (points summed over the races, a
running race provisionally, the same cutoff), and nobody advances.

A showcase stays out of everything the site shows about the event. The detail
lists it apart, in `showcases`, never in `stages`, so the bracket, the
timeline, the format block, the phase (a showcase never holds the season
open), the current and next stage, the live race (home band, navbar dot) and
the Open Graph line-up never see it; its date is bound neither by the stage
order nor by the event window. Its races are still attached to the event, so
the counts read straight off the event's races leave them out by hand: the
players and their previews in the summary and on the Open Graph card, and
the signature weapon, so a runner seen only in a showcase is no entrant.

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
`stage:<stage key>` per dated stage, in stage order. When stages have no
config date, one `playoffs` stop stands for every match scheduled with the
players: it sits where the first of those stages sits in the list (a
newcomers' final listed before the quarters comes before it), dated by the
earliest match scheduled among them, kept between the stops around it so the
rail never runs backwards, and, before any match is scheduled, at the date of
the stop before it. `announce` uses `announced_at` when the config sets it,
otherwise `starts_at` minus 7 days.
The same date is the newcomer cut (see Scoring), which is why a `newcomers`
stage requires `announced_at`: a final's field must never hang on a default.
The Playoffs stop shows no date line on the page: its date only places the
ridden rail, each match carrying its own date in the bracket.

### Signups

While the event can still be joined (`upcoming` and `qualifier`), a signed-in
runner can say they are in: `POST /api/events/{slug}/signup` adds the row
(idempotent), `DELETE` removes it, both 204, 400 in any later phase. It is a
signal, not a gate: running a qualifier seed enters a runner anyway, and
withdrawing after a run changes nothing visible, since the runs keep them on
the ladder. `my_signup` on the detail tells the viewer's own state. It keeps
reporting the stored row after the cut, when the ladder no longer lists it.

## Phases

| phase       | when                                                                 |
| ----------- | -------------------------------------------------------------------- |
| `upcoming`  | before `starts_at`                                                   |
| `qualifier` | until `qualifier_ends_at`                                            |
| `cut`       | until the first stage date (a scheduled race dates an undated stage) |
| `playoffs`  | until `ends_at`, or until the last stage is complete                 |
| `finished`  | after                                                                |

The ladder is provisional until every attached qualifier race is FINISHED. A
stage is complete when it has all its races attached and FINISHED; its
advancing runners (its `advance`) then fill the stage it feeds automatically.

The admin events list computes `phase` without grouping the races by stage, so
it always treats the last stage as not yet complete. This only matters
between the last stage finishing and `ends_at`: in that window the admin list
still shows `playoffs`, while the public event page (which loads the stage
races) already shows `finished`. It also reads only the config's dates, so an
event whose first match is scheduled by its races stays `cut` there until the
first dated stage.

### Current and next stage

The current stage (`current_stage_key`, during `playoffs`) is the one with a
race RUNNING, the first in bracket order when two run at once; else a stage
played today in UTC, by its date or by any of its races (so a match spread
over two evenings stays current on the second): the first of the day that has
started (any attached race not in setup) and is not complete, else the first
not complete, else the last of them. The next stage (`next_stage`, on the
detail and the summary) is the earliest stage ahead with a date, not
complete, that waits on no stage without one: the final is not next while
a semi feeding it is unscheduled,
while the newcomers' final, drawn from the ladder, can be. The Open Graph
card shows the current stage, else the next one.

## Scoring

A qualifier seed scores with the daily formula (`compute_daily_points`): 100
to first, proportional down the field, unfinished runs ranked by depth
reached then time, floor of 1, over runs with at least two zone entries. Only
settled runs (finished or abandoned) score: a seed stays open for days, so a
run in progress neither enters the ladder nor moves the other runners' points
until it ends; the seed card's `my_result` scores the same field. Playoff
races score differently, see Playoff scoring below. Ladder: best
seed per mode, summed over the modes; a score in every mode is required to be
ranked; ties on the summed in-game time of the counted seeds. Newcomers have
fewer than `newcomer_threshold` finished races started before the
announcement (the timeline's `announce` stop), not the opening: what a player
had played when they learnt of the event is what counts, so practising during
the announcement week neither costs nor earns the status. Daily seeds are
races, so they count towards that; solo sessions are not, so they do not. The
format block names daily seeds explicitly, since "races" alone reads as
organised races to a player who mostly runs the daily.

A seeded stage's `seeds` index into the sorted ladder position by position
(seed 1 is the top entry, seed 2 the next, and so on), not by each entry's own
displayed rank. Tied runners occupy consecutive positions sharing the same
rank, so a seed number can resolve to a runner whose displayed ladder rank is
lower than the seed itself (e.g. a three-way tie for rank 1 means seed 3 also
holds a rank-1 runner). A runner with no scoring qualifier run (on every
attached seed, fewer than two zone entries or a run not yet finished or
abandoned) is not on the ladder: the ladder's `entered` count is the number
of runners with at least one scoring run, not the number who joined a
qualifier race.

While the event can still be joined, the ladder closes with the signed-up
runners who have no scoring run, in signup order, without rank, score or
counted mode (`signed_up` counts them, `entered` does not); from the cut on
they leave it. Seeding reads only ranked entries, so a signup never resolves
a seed or a newcomers' slot.

Qualified groups map each seeded stage's `seeds` to ladder positions. The
runners ranked after the largest seed form the bench. The config's
`withdrawn` names are replayed in their order: a withdrawal of a runner
holding a seat (a seed, or an earlier replacement) vacates it and hands it to
the first bench runner neither called up nor withdrawn so far, shown under
their own position ("Seed 33"); a withdrawal of a bench runner only keeps
them from being called up. A replacement once called up stays put whatever
is declared after, and only seeded stages call anyone up: a runner who gives
up a fed stage leaves it one short. The newcomers' group takes the first
ranked newcomers positioned after the last seed or the furthest runner
called up, withdrawn ones skipped. A seat nobody can fill reads "TBD" while
the ladder is provisional and "No runner" once it is final; a seat past the
end of a provisional ladder keeps its "Seed N" placeholder. The ladder
itself is unchanged by a withdrawal, and a stage that has raced shows its
results, so a late edit of the list changes nothing it already displays. On
the page, the seeded stages' boxes are titled Group A, Group B and so on; a
box whose stage carries that same label shows its round's name ("Round of
32") in its meta line instead of repeating it.

### Playoff scoring

A stage or showcase race scores on the event's own table
(`score_playoff_race`), never the daily formula. Only the runs finished by
the race's end score: `playoff_points` by in-game time, equal times sharing a
rank, the table's last value for every finisher past it (a showcase can field
more runners than the table has entries). Every other runner of the race is a
DNF on 0 points: an abandoned run, a run cut off at the race's end, a runner
who never started, and, while the race runs, a run still in progress, so the
bracket moves at the finish line only. The table must be positive and never
rise down the ranks, so a finish always outscores a DNF.

The cutoff: when a race's first runner finishes, the server gives the race a
`race_duration_minutes` so that `race_ends_at` falls on the first minute of
the race clock at least `playoff_cutoff_minutes` after that finish
(`start_playoff_cutoff`, called by the finish handler), and pushes a
`race_info_update`. The mod counts the time left down, the race page and the
cast scenes show it, and the hard-close loop then ends the race, turning the
runs still going into DNFs. The loop polls every 10 seconds, so the finish
handler rejects a finish landing after `race_ends_at` in the meantime
(`race_not_running`, as on a closed race), and scoring counts a finish
recorded after it as a DNF: the countdown is the rule. Only the first
finisher sets the deadline, so an organizer can still extend it through
`PATCH /races` (a crashed game, say) without a later finisher shortening it
back; an earlier deadline already set stands, and a race that ended in the
meantime gets none. A reset drops the deadline (an organizer's own cap on a
playoff race included), so the replay's first finisher sets a fresh one. The
cutoff runs on the wall clock, which the stream shows, while the ranking
stays on in-game time.

Evenings sum the points of their races; ties on the summed in-game time, in
which a DNF counts as its race winner's time plus the cutoff (or the slowest
finisher's, if slower), however early the run stopped, so abandoning early
never buys a better tie-break. Runners still tied (two who finished nothing
all evening share both) rank by the summed layer reached, then by user id: an
arbitrary but fixed order, so the page never flips between loads, which the
bracket applies to who advances (the site has no override for a tie settled
otherwise). A race nobody has finished lists nobody and counts for nothing,
not even for the tie-breaks: stage races are created with their runners
ahead of the evening, and the bracket keeps showing the field until the first
finish.
A running race scores provisionally, so the bracket shows a stage's points in
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
viewers. While the event is upcoming `qualifier_races` is empty, whatever is
attached: the seed cards render as placeholders carrying the opening date,
and the races being checked stay off the page (see "Running an event"
below). The gate follows the phase, so a `phase_override` moves it too. From
the opening on, a qualifier race still in setup shows as upcoming on its
card, "Not open yet", with no play strip whatever its registration state.
`closes_at` is the race's
`started_at + race_duration_minutes`, the same instant as the race's own
`race_ends_at`.

The seed cards of a mode sit two to a row, one at 900px and narrower. With
three seeds per mode they share one row once the page has its full width
(1200px and up), the play strip narrowed from 64px to 52px so the mode name
and the avatars with the time left still fit; four seeds keep two by two.

In game, a qualifier seed replays like a Daily Seed: once the runner is
playing, the overlay's leaderboard is projected to their own IGT, so the
other runners appear where they stood at that time instead of as a settled
field of finishers. The web race page and the ladder keep the real state.
See the "In-mod replay leaderboard" section of
[DAILY_SEED.md](DAILY_SEED.md#in-mod-replay-leaderboard). Unlike a Daily
Seed, a qualifier shows no bloodstains at the fog gates: the server sends
mods no `death_counts`, since the deaths of the week's early runners would
point a later one to the costly zones. The race page header leaves out the
"Private" badge every qualifier race would carry (private here only keeps
the race out of the Discord announcement) and the elapsed clock, since the
time since the opening measures nobody's run. The page also drops the info
panel (participants, dates, late join, duration, deathless), which every
qualifier race shares: its schedule, late join, duration and deathless
settings are edited through the API, not from the race page.

The race page leaderboard shows each settled run's points in the row's
top-right slot, as a closed Daily Seed does: a scored finished or abandoned
run (at least two zone entries) carries `+XX` in brass while the seed is open
(the provisional points of the seed card and the ladder, moving as more runs
settle), in verdigris once it has closed; a run in progress keeps its layer
count there. See `daily_points` in
[PROTOCOL.md](PROTOCOL.md).

## Running an event (admin)

1. `/admin`, Events tab: create the event from the template, adjust dates,
   modes and stages, save. Mode keys must be pool names. A rejected save
   shows the server's validation errors next to the JSON editor, each
   prefixed with its field path. A save is also rejected when the new config
   would orphan a race already attached to a slot it no longer has room for
   (a removed or renamed mode, stage or showcase, or a lowered
   `seeds_per_mode`): the error names the orphaned slots, and nothing is
   stored until the races are detached from the Races tab.
2. Before the qualifier: `tools/qualifier.py create` (usage in its docstring;
   `--dry-run` shows what it would do) creates the race of every empty
   `qualifier:<mode>:<n>` slot and attaches it, named "SEASON ONE QUALIFIER -
   STANDARD - SEED 1" with the organizer racing it, and leaves the slots
   already taken alone, so a rerun fills the slots a failed run left empty. It
   is refused once the qualifier has opened, since a race created then would
   still last the whole window and close past the cut. A race made by hand
   takes the same settings in the normal form: the mode's pool under Game Mode,
   "I'll race" as your role, "Private" visibility, "Invite only" registration,
   and under Advanced options, Late joiners and Auto-end both at the
   qualifier's length in minutes (10080 for a week; attaching refuses two
   different values), then an attach to its slot from the Races tab. Attaching
   sets `exclude_from_stats` and hides the race from the public listings. To
   check a seed, release the seeds, download the pack as the organizer (a
   participant of the race), and re-roll a seed that does not suit (a re-roll
   withdraws the release). A second account added through the race page's
   "+ Invite" search to check a seed must be removed once satisfied: a race
   started with it registered keeps it on the seed's card all week, and the
   script below reports it (the organizer is not counted). Registration stays
   closed until the opening because a race id gets around (the organizer's
   public activity lists every race they organize): closed, it leads nobody to
   a released pack.
3. The opening: `tools/qualifier.py start` opens every qualifier race at
   `starts_at`. Run it with `--dry-run` first: it flags a slot with no race, a
   race still holding a participant other than its organizer, a duration that
   does not end at the cut, a public race, and a registration already open.
   Then leave it running, logged in to the site (logging out replaces the token
   it uses): shortly before the opening it opens registration (100 places, the
   server's cap), releases the seeds still withheld, and sends the start calls
   at the opening minus the server's countdown, so each race's `started_at`,
   and so its close, lands on the event's dates. Started by hand one after the
   other, the last races would close minutes after the cut, and a run finished
   in that gap still counts. A race whose registration could not be opened
   stays in setup (a started race's registration can no longer change): fix it
   and rerun with `--now`, which is refused before the opening (it would open
   every seed early) unless `--before-opening` is added for a trial on a local
   server. A race started late can have its `started_at` moved back to
   `starts_at` in the database, never forward (a `started_at` still ahead reads
   as a countdown); the edit is not broadcast, so a connected mod keeps the old
   deadline until it reconnects. During the week that follows: nothing. To void
   a broken seed, detach it.
4. Once a match is agreed with its players: create the stage's public races
   (four slots, a duration cap) with their `scheduled_at`, add the qualified
   runners and the casters, attach to `<stage>:<n>`. The earliest of the
   stage's races then dates it, which ends the `cut`, makes it the next
   stage, and drives the home band, the share card and polling (see
   "Current and next stage" and "The event page"). Fixed evenings (the
   newcomers' final, the final) keep their config date instead; create their
   races the same way, whenever the players are ready, on that date. Name
   the races "Semi B - Race 1 - Standard", hyphenated like daily races: the
   race cards beside the bracket display the race name without the stage
   label the section already carries ("Race 1 - Standard"), and drop the
   players / mode / organizer foot row and the viewer's role mark, since the
   bracket beside them lists the field and each stage's date and modes (an
   organizer or caster finds their role on the race page). The casters build
   their OBS scenes from the Cast Setup panel on the race page, and point the
   talk scene at the stage rather than at one of its races, so it stays up all
   evening (see [CAST_OVERLAYS.md](CAST_OVERLAYS.md)). A slot with no
   race yet shows a placeholder named the same way, carrying the stage's
   expected runners as an avatar stack. Start each race as its organizer on
   the evening.
5. A qualified runner withdraws before their group plays: add their Twitch
   username at the end of the config's `withdrawn` list and save; the page
   hands the seat to the next runner on the ladder, whom the organizer tells.
   If that runner declines too, add them as well.
6. A showcase (see "Showcases" above) runs the same way: add it to the
   config's `showcases`, create its races with the chosen runners and the
   casters, named after its label like a stage's ("Ignite Showcase - Race 1 -
   Standard"), and attach them to `<showcase>:<n>`. Its field is read off its
   races, so until one of them is attached its race cards list nobody:
   create them ahead, runners registered. The casters point the talk scene
   at the showcase as they would at a stage. Cast Setup only offers the
   events on the bill (from the announcement to a week after `ends_at`), so
   a showcase held outside that window needs its talk URL written by hand.

No manual transition exists: the page follows the dates and the race states.
`phase_override` is the escape hatch for schedule accidents.

### Attaching a race to a slot

`POST /api/admin/races/{race_id}/event` with `{event_id, slot}` attaches a
race; `{event_id: null}` detaches it, clearing both `event_id` and
`event_slot` and leaving `exclude_from_stats` unchanged. Attaching validates:

- The slot must exist for the event's config (a known mode and seed index for
  a `qualifier:<mode>:<n>` slot, a known stage or showcase and race index for
  a `<stage>:<n>` slot).
- A `qualifier:<mode>:<n>` slot requires the race's seed pool to equal the
  mode key, and `late_join_window_minutes` and `race_duration_minutes` both
  set and equal; attaching then sets `exclude_from_stats` on the race.
- A stage slot requires `max_participants` to be null or at least the stage's
  field size: the number of `seeds` for a seeded stage, `size` for a
  newcomers stage, the sum of its sources' `advance` for a stage fed by
  others. A showcase slot takes any `max_participants`, having no field.
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
during the qualifier it only refreshes on page reload. An upcoming page
reloads its data at the opening, up to ten seconds after it (spread over the
viewers), and a few more times five seconds apart while the answer still
reads upcoming (a clock ahead of the server's), so the seeds appear without a
reload.
All dates and times render in the viewer's browser timezone, and the instants
still ahead of the viewer name that timezone too ("Wed 30 Sept, 21:00 CEST"):
the take-part steps, the seed cards' opening, the qualified groups with the
`Cut` tile beside them (that block only shows before the cut), and the stage
whose races the bracket block lists. What the viewer can no longer act on
keeps the plain form: the ladder's `Closed` fact, the same deadline read
after it passed, and the phase signal.

From the cut on, the bracket block lays the playoffs out as a tree: one
column per round (a seeded stage opens it, a fed stage follows its deepest
source), each stage centred on the stages it takes runners from, connectors
between them, the final leading to the Champion. With four first-round boxes
or more (quarters) the tree takes the page's width: a side column holds the
evening section on top, level with the "Bracket" title, and the Champion on
the final's axis; the playoff rules sit under the first column and the
newcomers' final under the final, level with the last first-round box. Under
900px it becomes one column, the evening first. A shorter tree (two semis)
keeps the older arrangement: the tree with a narrow Champion column, the
evening section and the rules beside it. A stage without a date reads "Date
to be agreed", and the evening section disappears while no evening is
current or next.

The format block keeps its dates to the day, in brass. Its playoffs paragraph
counts the places (the seeded stages' seats), says the rounds without a fixed
date are "scheduled with their players", naming a `round` stage's round after
its seats ("the round of 32, quarters and semis"), and lists the stages the
config dates. When every stage has a fixed date it closes with the time the
evenings start at ("Playoff evenings start at 21:00 in your timezone");
otherwise each fixed evening carries its own time ("then the Final on Sun 25
Oct at 20:00"), and so does the newcomers' final. `stageTimes` reads the shared
time from the stage dates: one time when they share it, plus the single evening
that falls elsewhere when exactly one does ("the Final at 20:00"), and nothing
when no single evening stands out against a majority: three or more times, an
even split, two evenings that merely differ, or a lone stage. A season
scheduled so that two evenings fall either side of a daylight saving change,
out of four, loses the line for the viewers that change applies to, and for
them only. Only the wall clock counts, never the zone's name, so evenings kept
at one local time across a daylight saving change still read as one time. That
change is the ordinary case rather than a corner one: the real season's last
evening is the Sunday Europe leaves summer time.

The take-part steps start on the viewer's own state. Step 01, "Sign up for the event", is
one primary button, `I'm in`, whatever that state: signed out, it parks the
return to the page and a signup intent (the event and the time, good for ten
minutes) in `sessionStorage`, goes through Twitch, and the page honours the
intent once the callback has landed the viewer back signed in. A browser back
from an abandoned login spends the intent; one served from the browser's
cache, which never mounts the page, leaves an intent that expires instead of
signing anyone up on a later visit. Signed in, it calls the signup directly,
under a verdigris line with the viewer's name (and their avatar when they
have one), so the account they engage with is in view.

Once they are in, the button gives way to a check line `You're in` with a
quiet `Withdraw` beside it; the page reloads the event right after either
call, so the ladder row appears or goes without a page reload. An empty ladder reads `Nobody in yet.` while the event is upcoming
and `No runs yet.` from the qualifier on. A call that fails shows its reason
under the control and reloads the event, so a viewer whose session expired
or who clicked after the cut sees the step correct itself.

Practice has a block of its own before the seeds, because the qualifier does
not forgive a first contact with the game: one card per mode, linking through
`soloPoolPath` to `training_<mode key>`. The solo page keeps its own default
when that pool does not exist or has no seed left, so a mode with no solo
counterpart degrades quietly. Each card carries that pool's count, from the
public pools endpoint the block fetches itself: the seeds it holds, or how
many of them this viewer has run (`soloSeedLabel`, which names the thing
while the counts are in flight). The seeds block itself says nothing about
practice: with a block above it, a link on every mode group was weight, not
help.

Signed out, the cards lead to Twitch and come back to the solo page on the
mode they named, so the click keeps its intent; the introduction closes on a
primary `Try a seed` button, the home page's own call, and a "How it works"
beside it; the button stores no redirect, so the callback lands on the
dashboard and its onboarding. A signed-in reader gets neither, having
answered both questions by being there.

While the event can still be joined (`upcoming` and `qualifier`), a "What is
SpeedFog?" section opens the page for visitors who have never played: three
concepts beside the trailer looping muted, its frame a link to the trailer
with sound on YouTube, with a chip in the corner saying so. The media are
constants at the top of `EventIntro.svelte` rather than event config. The loop
plays muted and inline, with a play/pause button for every viewer, and starts
paused for a viewer who prefers reduced motion.

The loop is the trailer re-encoded for the web with `ffmpeg` (854x480, 30 fps,
H.264 CRF 27 in `yuv420p`, no audio, `faststart` so the index leads the file
and playback starts before it lands, faded out before the date card), a few
megabytes instead of the hundreds of the source. The source stays out of
`web/static/`, which ships whole into every build and every deploy archive.

Once the phase
is `finished`, two compact plates under the band crown the final's and the
newcomers' final's winners (the leader of each complete stage), the champion's
larger, with their story: the position they qualified at on the ladder, the
evening's races finished first out of the races expected (a race nobody
finished counts for no one), and their signature weapon, the one carried the
longest over every event race they entered, showcases aside
(`signature_weapon` on each stage result, from the zone histories). An event that ends at `ends_at` with the
final incomplete shows no plate.

### Seeing each state locally

`tools/simulate_event.py <stage>` fills a local database with a whole
simulated season and projects it at the state named by the stage, shifting
every date so that state is the current one: the announcement, the open
qualifier, the cut with no race attached, the newcomers' final live and
played, Quarter C live beside two played quarters and an unscheduled one,
the quarters over with no semi scheduled, Semi A live, and the final live and
finished. The event must already exist, and its modes and stages must match
Season One's real configuration, which the tool reproduces (its showcases
stay empty). It writes fabricated participations onto real user rows,
detaches every race it does not manage from the event, and consumes an
available seed for each of the thirty-three races it creates (a pool out of
fresh seeds lends its latest consumed one), so it refuses a database that is
not on this machine. On a database restored from production, the real event
carries the real qualifier runs, which a run would wipe: the tool refuses an
event holding a run with mod activity (unless `--force`), so copy the event
under another slug and pass `--slug`.
`--viewer <twitch username>` gives that runner a seed of every card state.
`--exclude <twitch username>` (repeatable) keeps that user out of the roster,
runners, casters and organizer alike, so a real account can join a qualifier
seed by hand and see the field as a newcomer would, until the next run of the
tool clears the participants again.
The states before the cut also sign up the viewer and a dozen runners, so the
ladder's signup rows and the upcoming card's avatar row show.

## Home page and navbar

An event is on the bill from its announcement (the timeline's `announce`
stop) until `FEATURED_TAIL` (seven days) after `ends_at`, whatever the phase.
While it is, `GET /api/events` lists it as a summary that the home page, the
dashboard and the navbar read through the `featuredEvent` store, which
features the first entry: the layout refreshes it whenever the signed-in
state changes, the two pages on mount. When two events overlap, a finished
season (kept for its champion) yields the head of the list to one still to
come, so a season announced right after the last final is what the band
shows; otherwise the earliest season leads.

The summary carries the phase, the `players` count and `player_previews`
under the Open Graph card's rule (everyone who joined an event race other
than a showcase's, plus the signups while the event can still be joined, the ladder's best first;
the first `MAX_PLAYER_PREVIEWS` of them are previewed; both empty while an
upcoming event has fewer than `MIN_UPCOMING_PLAYERS`), the next stage, the
live playoff race with the slot it fills (`live`), the champion once the
final is complete, and `my_signup`. It skips the newcomer flags (the
detail's only database work beyond the load) and the signature weapons. An
event whose stored config no longer validates is left out rather than
breaking the home page.

`EventBand` sits between the hero and the Daily Seed on the home page and
above the Daily Seed on the dashboard: the event page's lockup (a link to
that page), a phase signal, one line of state and the buttons, which
`eventBand` in `lib/events.ts` decides from the phase:

| phase       | line                                        | buttons                                                                      |
| ----------- | ------------------------------------------- | ---------------------------------------------------------------------------- |
| `upcoming`  | the opening, then who is in                 | `Take part`, to the event page                                               |
| `qualifier` | the closing, then who is in                 | `Take part`, to the event page                                               |
| `cut`       | the next evening, when one is known         | `Event page`                                                                 |
| `playoffs`  | live: stage and race index; else next stage | live: `Watch on Twitch` or `Race page`, then `Event page`; else `Event page` |
| `finished`  | `Champion`, then the champion's link        | `Event page`                                                                 |

Who is in shows as the race cards' avatar stack after the line (initials for
a runner without an avatar, the name on hover, a `+N` chip for the players
beyond the previews), while the event can be joined and someone is.
Signing up stays on the event page: a viewer already in reads `You're in`
next to the `Event page` button. The watch link follows the live strip's
rule (a live caster's own stream, else the first caster's channel). The
instants on the line are ahead of the viewer, so they carry the timezone
like the event page's.

The navbar shows an `Event` link to every viewer while an event is on the
bill, before Solo when signed in and before the login button otherwise,
underlined on event pages and carrying a red dot while a playoff race runs.

## Open Graph

Sharing `/events/<slug>` unfurls a card rendered by the server, like race and
daily pages: nginx routes known crawlers to `GET /api/og/event/{slug}/meta`,
whose tags point at `GET /api/og/event/{slug}.png`.

The card follows the phase, on the same computation as the page
(`summarize_event` in `services/og_image.py` reuses `event_service`):

| phase             | body                                                                                                      |
| ----------------- | --------------------------------------------------------------------------------------------------------- |
| `upcoming`        | the day the qualifier opens; from ten players in, their row of avatars under it                           |
| `qualifier`       | every entrant as one row of avatars, then the closing day                                                 |
| `cut`, `playoffs` | the current stage's line-up by name, else the next one's (see Current and next stage); the stage and date |
| `finished`        | the winner of the final                                                                                   |

The header carries the phase, the co-brand lockup sits under it with the
partner logo, and the footer holds the entrant count and the event window.
Entrants run in ladder order (best first), capped at 14 with a `+N` chip. A
line-up slot nobody holds yet is a dashed ring labelled with what it waits on:
a seed number for a seeded stage, the source stage for a fed one. A finished event
whose final never happened, and a `cut` or `playoffs` card with neither a
current nor a next stage, both fall back to the entrant row.

Signups count as entrants while the event can still be joined: after the
scored runners on the qualifier card, in signup order, and on the upcoming
card once ten players are in (`MIN_UPCOMING_PLAYERS`). Below that the
upcoming card carries neither the row nor the footer's player count, so a
young event advertises its opening day rather than how few have committed,
and its cache key does not move with the signups.

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

- `GET /api/events`: the events on the bill (`EventSummaryResponse`, see Home
  page and navbar).
- `GET /api/events/{slug}`: everything the page renders (`EventDetailResponse`),
  plus the showcases, which only the talk cast scene reads.
- `POST /api/events/{slug}/signup` and `DELETE /api/events/{slug}/signup`:
  the viewer's own signup (see Signups).
- `GET /api/pools?type=training`: the practice cards' seed counts, the page's
  only other call. Public, with `played_by_user` filled in for a signed-in
  viewer.
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
