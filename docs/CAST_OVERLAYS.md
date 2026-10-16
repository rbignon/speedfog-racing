# Cast Overlays

Six full-screen OBS scenes for a caster running a broadcast: quad, focus,
duel, metro, browser and talk. They are a different kind of overlay from the
two existing ones, `/overlay/race/[id]/dag` and
`/overlay/race/[id]/leaderboard`: those are
transparent widgets a caster places anywhere on a scene they build themselves
(a DAG in one corner, a leaderboard strip along an edge, sized and positioned
by hand in OBS). A cast scene owns the whole 1920x1080 frame instead. It
paints an opaque plate over the entire canvas, cuts holes out of that plate at
fixed positions, and leaves those holes for the caster's own video sources
(webcams, captured Twitch POVs, a capture of the caster's own browser) to show
through from underneath. The browser source is the top layer of the OBS
scene; everything else sits below it.

## Composition model

Each scene renders at a fixed 1920x1080 design canvas (`CANVAS` in
`web/src/lib/cast/layout.ts`), scaled down by the page itself to whatever
size the browser window or OBS Browser Source actually gives it, so the
Browser Source should always be added at 1920x1080 to avoid a second, OBS-side
rescale on top of the page's own.

The canvas has two kinds of content:

- **Holes** (`CastRect`, one of the roles `pov`, `hero`, `cam`, `map`, or
  `browser`): a rectangle the plate does not paint over. An SVG mask
  (`maskDataUri`) cuts these out of the opaque plate, so whatever OBS source
  sits directly beneath
  the Browser Source in the scene's source list shows through exactly there.
  The caster places one video source per hole, at that hole's position and
  size, underneath the Browser Source. A `pov`/`hero` hole for a slot nobody
  is seated in (a field smaller than four; see `resolveSlots` below) is never
  pierced: `CastPlate`'s `seatedSlots` prop, computed by the quad and focus
  pages from the same seating they render, keeps that rectangle part of the
  opaque plate instead of broadcasting a framed, numbered hole onto whatever
  sits underneath. The guides mode still outlines every hole, seated or not,
  since a caster sets OBS sources up once for a scene that could seat a full
  field.
- **Panels**: rectangles the scene draws itself on top of the plate (race
  name, lockup, clock, standings, runner cards, the log, the metro map).
  These need no OBS source: the page renders them directly.

Every rectangle for every scene, hole or panel, comes from one module,
`web/src/lib/cast/layout.ts`, so the mask, the on-screen position guides and
the setup panel's position table can never drift apart from each other or
from what actually renders.

### Position guides

Adding `guides=1` to any scene's URL draws a dashed gold outline over every
hole with a label reading `LABEL  x,y  wxh` (`formatGeo`), directly on the
live scene. It is how a caster lines OBS sources up under the plate: open the
scene with `guides=1`, drag each video source's transform until it matches
its outline, then drop `guides=1` for the real broadcast. Guides mode also
numbers each POV frame with its slot (the `p1`..`p4` it takes), a chip the
live scene leaves out: on air it would sit beside the runner card's rank, a
second number per runner.

### Field-size overflow

A panel's rect is fixed, but the field it lists (standings, a race's
finishers) is not: a race can seat far more than the four runners every
scene was first validated against. Every panel that lists a variable-length
field caps how many rows it shows to what its own rect actually fits, using
`rowCapacity`/`planRows` (`web/src/lib/cast/rows.ts`): the row count is
computed from the rect's own height and the panel's row height, never a
typed constant, so a bigger field (or a rect that changes) can never print
past the panel's bottom. Once the field doesn't fit, the panel's last row is
given up to a quiet "+ N more" line, the same phrasing the in-game overlay's
own leaderboard footer uses for the same situation (`mod/src/dll/ui.rs`).
Four panels do this: `CastStandings` (metro), `CastMiniStandings` (focus),
`CastRoundStandings` and `CastRaceCard` (talk). The metro scene's
`CastStandings` additionally takes a `lines` URL parameter (see below)
letting the caster show fewer rows than the panel fits; nothing lets any of
them show more than the panel's own capacity allows. The quad scene's four
runner cards seat exactly four runners by construction (see `resolveSlots`)
and need no cap.

## The six scenes

Five of the six scenes (quad, focus, duel, metro, browser) share a **desk**
band along the bottom (the quad's is thinner, see Quad): a race name panel, a
caster lockup (the SpeedFog Racing wordmark, crossed with the event's
co-brand when one is set), a clock panel, and up to two caster cam holes.
How many cam holes it cuts depends on the `cams` parameter (0, 1 or 2); with
0, the desk still draws its race/lockup/clock panels but pierces no cam holes
at all. The clock panel shows one element
per state: the race clock alone while the race runs (its ticking says the
race is live, so it carries no Live tag; "IGT cutoff" joins it on a race
with an in-game cutoff, otherwise "Ends in" once the race has a deadline),
and in its place a large "Upcoming" before the start and a large "Finished",
in the finished colour, once it is over. The server runs a race from the
organizer's start command on, its start (`started_at`) a countdown later:
through that countdown the panel stays "Upcoming", with "Starts in 0:07"
under it, rather than a clock frozen at 0:00.

Before the start, the field stands in join order, the only order there is:
no runner card (quad, focus, duel) shows a rank digit or the leader's brass,
the standings panels (metro, focus) number no row, and the metro map stays
hidden. The start countdown still counts as before the start (each scene
reads the race status through `sceneStatus`, which shows a race still
counting down as setup, its own `delay` included): ranks, the leader and the
map appear the moment the countdown ends.

| Hole  | Position (x, y) | Size (w x h) | Shown when  |
| ----- | --------------- | ------------ | ----------- |
| CAM 1 | 408, 776        | 384 x 288    | `cams >= 1` |
| CAM 2 | 1128, 776       | 384 x 288    | `cams >= 2` |

That is the full desk, 288px tall, of the focus, duel, metro and browser
scenes.

The desk's own panels (not holes, no OBS source needed): the race-name panel
at (16, 776), 376 x 288; the lockup at (820, 776), 280 x 288; the clock panel
at (1528, 776), 376 x 288.

### Quad

Four runners in a 2x2 grid, filling the main area above the desk. Each POV
hole has a runner card beside it (avatar, name, rank, layer progress); the
right column's cards are mirrored to face inward, toward their POV. The
cards sit in slot order, not in a ranked list, so the first runner's gap
row names the role instead of standing blank: Leader while the race runs,
Winner once it is over (the ranked standings panels keep their usual empty
cell). A finished runner's IGT takes the finished colour, as on the duel
cards and in the standings, and their zone line reads "Finished" in that
colour (every finisher stands in the final boss's zone, so the line has
nothing else left to say); a runner out of the race keeps the zone they
stopped in, their Gap row reading DNF or DQ. The focus scene's hero card
does the same. A card's name keeps one line, ellipsized at the card's width,
its badge whole beside it or on the next line.

The quad has a desk of its own, thinner (216px instead of 288, Ignite's
pick in October 2026): its four POVs, too small at a third of the canvas
(640 x 360), take the 72px it frees, and the cards take the width the POVs
leave, 216px each. The other race scenes keep the full desk: their POVs are
bound by the width and could not grow from it. The cams therefore change
size and place when the broadcast cuts between the quad and another scene;
each OBS scene has its own sources anyway.

| Hole | Label | Position (x, y) | Size (w x h) |
| ---- | ----- | --------------- | ------------ |
| pov1 | POV 1 | 248, 16         | 704 x 396    |
| pov2 | POV 2 | 968, 16         | 704 x 396    |
| pov3 | POV 3 | 248, 428        | 704 x 396    |
| pov4 | POV 4 | 968, 428        | 704 x 396    |
| cam1 | CAM 1 | 504, 848        | 288 x 216    |
| cam2 | CAM 2 | 1128, 848       | 288 x 216    |

The quad desk's panels: the race name at (16, 848), 472 x 216; the lockup at
(820, 848), 280 x 216; the clock at (1432, 848), 472 x 216. The runner cards
sit at x 16 and 1688, at the POV rows' y, 216 x 396.

### Focus

One runner large (the "hero"), the other three stacked small on the right,
for commentary that has settled on a single runner without losing sight of
the field. Which POV slot (1 to 4) becomes the hero is the `focus` parameter;
its own zone splits render beside it.

| Hole                     | Label              | Position (x, y) | Size (w x h) |
| ------------------------ | ------------------ | --------------- | ------------ |
| hero                     | HERO (POV `focus`) | 272, 16         | 1296 x 729   |
| pov (1st remaining slot) | POV n              | 1584, 16        | 320 x 180    |
| pov (2nd remaining slot) | POV n              | 1584, 212       | 320 x 180    |
| pov (3rd remaining slot) | POV n              | 1584, 408       | 320 x 180    |

The three small POV holes are whichever slots `focus` did not pick, in slot
order. A mini standings panel sits at (1584, 604), 320 x 148 (rank, colour
dot, name and gap; no depth cell, since the scene's own POVs already show
what each runner is doing), and the hero's own runner card fills the panel
at (16, 16), 240 x 736, left of the hero hole, so the scene reads card,
hero, field, left to right. The name keeps one line, ellipsized, as on the
quad cards. When the badge wraps under a long name and the weapon line takes
two lines, the splits at the card's foot are what give way, a whole row at a
time; the zone line above them never does. Plus the
shared desk band.

### Duel

Two runners head to head, each at the biggest 16:9 the main area fits side
by side, for a showcase match or any race the commentary treats as a duel.
Under each POV sits that runner's card (avatar, name, rank, zone, weapons,
deaths, IGT; the right card mirrored to face inward, like the quad scene's
right column), and between the cards a versus block in three columns: each
side's depth in the outer column next to that runner's own card, and in the
middle the head-to-head gap between the two seated runners themselves,
whoever else is in the race: the leader gap's formula with the one ranked
ahead standing in for the leader and its own splits (`layer_entry_igts`, see
`computeGapBetween`), never the difference of their leader gaps, which reads
0:00 once both overran the leader's time on a shared layer. It reads negative
while the runner behind, on a shallower layer, is ahead on IGT (the runners'
IGTs drift apart over a live race, see `docs/PROTOCOL.md`). With it comes who
leads (the one ranked ahead), and once neither side is still racing
(finished or out) who settled it: "wins" for the race's own winner (ranked
first once the race is over: finishers rank by in-game time, so a runner
still on course may yet finish under the first's time), "ahead" otherwise,
since the scene can seat any two runners of the field and the better of the
3rd and the 4th won nothing. A gap not known yet
(splits in flight or held back by the caster delay, or a race not started)
shows `–`, never a tie. Deaths stay on the cards, not repeated in the block.
The duel cards have no Gap row, so their zone line carries the runner's
state: a runner out of the race reads DNF or DQ before the zone they stopped
in ("DNF · Stormveil Castle"), and drops out of the gap (the surviving side
leads); a finished runner's zone line reads "Finished" and their IGT takes
the finished colour, as in the standings panels.

| Hole | Label | Position (x, y) | Size (w x h) |
| ---- | ----- | --------------- | ------------ |
| pov1 | POV 1 | 16, 16          | 928 x 522    |
| pov2 | POV 2 | 976, 16         | 928 x 522    |

Panels: the two runner cards at (16, 554) and (1468, 554), each 436 x 198,
and the versus block between them at (468, 554), 984 x 198. Plus the shared
desk band.

### Metro

The seed's whole zone graph, drawn live, with a log of recent zone entries
and outcomes beneath it, beside a full standings panel. The map itself is not a hole: it is
listed in the layout only so the guides mode can draw its box, since it
carries no video and the page renders it directly in that same rectangle (at
16, 16, 1888 x 482).

| Panel                   | Position (x, y) | Size (w x h) |
| ----------------------- | --------------- | ------------ |
| Map (drawn, not a hole) | 16, 16          | 1888 x 482   |
| Log                     | 16, 522         | 900 x 230    |
| Standings               | 932, 522        | 972 x 230    |

Plus the shared desk band (cam holes only; the map takes the space the other
two scenes give the four POV holes).

Until the race runs (and on any status it does not know) the map box draws
no map at all, only "Map revealed at race start.": the scene goes on air, and a caster may not see the seed before the
start either, the same rule the race page applies to anyone but the field and
the organizer. The Cast Setup panel's preview is this same scene, so it hides
the map too.

Once the race runs, the map shows the whole seed at once, start on the left
and final on the right, so a viewer reads at a glance how far into the race
each runner is.
A seed is far wider than the box is tall (a 35-layer Boss Rush is about 7:1,
the box under 4:1), so the graph grows taller to fill it (MetroDagFull's
`fillContainer`, through `stretchToAspect` in `web/src/lib/dag/layout.ts`):
the space between its top and bottom rows spreads by up to
`FILL_MAX_ROW_STRETCH` (1.4, past which diagonals turn steep and the graph
looks squeezed), and the rest of the height becomes equal free bands above
and below, where the runners' names go. The nodes' own zone names are left
out: at this zoom they would render at about 5px (measured: 4.7px on a
35-layer Boss Rush, 5.5px on a 30-layer UWYG seed). Each runner's tag names
their zone instead, a second line under their name (the route label's last
leg, the place they stand, about 20px on air; LivePlayerDots' `tagZones`),
so the map still says where everyone is; a finisher's tag has none, the final
node says it. The runners' marks (tags, trails, death skulls) keep the size
they have at a 13-layer window however far the map zooms out, and the
nodes and edges grow partway (by the square root of the zoom-out), enough to
stay visible without crowding (MetroDagFull's `keepMarkSize`, with
`MARK_REFERENCE_WIDTH`).

Each runner on the map is a tag, as the reference mockup draws it
(`.mt-dot`, `.mt-line`, `.mt-name`): a still dot in a dark ring with a halo
in the runner's colour, a straight vertical connector, and the name in large
type at its end (`LivePlayerDots`' `playerTags`, instead of the orbiting
dots the race page shows). Runners on the same node sit side by side, and
finishers gather on the final node, past anyone still fighting there. A crowd at an edge of the map slides
inward as a whole. On the whole map, names go in the free bands, their
connectors reaching past the graph's outer rows (and past the node glyphs
there), and the free slot with the shortest connector wins: names stack in
the band nearer their dot until crossing to the other band is shorter. Each
dot keeps the stretch between itself and its own name free of other names,
so, while a free slot remains, a name never lands between a dot and that
dot's own name on the same vertical; only when both bands are full does a
name fall back over the graph
(`placeTags`' lanes, in `web/src/lib/dag/tags.ts`). In the follow view, with
no bands, each name points toward the middle of the window instead, where
there is room, and a name that would cover another name or another runner's
dot tries the other side, then one tier further out. A runner on the middle
row keeps a side of their own (from their colour slot), so a tag doesn't
flip because someone else moved. When no slot is free at all (a field
bunched in the first layers at the start of a race), a name takes the slot
in view that covers the least of the names already placed, then the least
of the other runners' dots: over a dot a name still reads, two names on top
of each other do not, and a name laid across a crowd would hide it.
Names stacked in a band leave the outer one's connector passing behind the
inner one: every name and zone line carries a halo in the plate's colour
(`LIVE_TAG_HALO`), so a connector stops at its letters instead of striking
them through. Names stay inside the window the viewport
shows (`FollowViewport`'s `visibleWindow`): in the follow view a runner on
the top or bottom row points inward, and a name near the left or right edge
slides in while its connector still leaves from the dot. A runner whose node
is off to the side (only possible with `maxLayers`, below) gets no tag at
all (the viewport's own side indicators cover those still racing); whether a
runner is on screen is judged by their node, not by where spreading put
their dot.

The map also reads its own query parameters directly, not through the
shared cast params, the same knobs `/overlay/race/[id]/dag` exposes:
`maxLayers` follows the runners with a window that many layers wide instead
of showing the whole seed, and brings the nodes' zone names back (the tags
then drop their zone line, the map naming every zone itself); `labels=0` or
`labels=1` forces the nodes' zone names off or on either way, the tags'
zone line following the opposite; `fontSize` sets their
size (default 9, down from the plain `/dag` strip's 11: measured against 7,
which read thin at broadcast distance, and against 11, which made a 90-node
seed illegible).

The log beside the standings ("Latest") merges every runner's zone entries,
newest first by in-game time, a death in a zone marked with a skull. Each
runner whose race is over also gets one row at their final in-game time:
"finished" in the finished colour, or DNF (an IGT cutoff included) or DQ in
the row's secondary tone, above any entry at the same time. `zone_history`
carries none of these, and they are the moments a caster most needs on the
feed.

The standings panel beneath the map is a single column, one row per runner
as the mockup draws it: rank, colour dot, name, zone, deaths, depth and gap.
A finished runner's gap cell shows their final time in the finished colour
instead of a gap that would read as if they were still racing; DNF and DQ
keep their plain-text marks. The focus scene's mini standings do the same.
A playoff race seats four runners, which is exactly what the panel fits; a
bigger field gets the row cap described in "Field-size overflow" above. It
also reads a `lines` query parameter (default: fit as many rows as the panel
allows), the same name and spirit as `/overlay/race/[id]/leaderboard`'s own
`lines`, letting the caster show fewer rows for a field they'd rather keep
short. It cannot ask for more rows than the panel actually fits.

### Browser

A web page of the caster's choosing (the race page, the event's bracket, a
runner's profile, the stats) over the whole main area, for commentary that
needs to show something the other scenes don't draw. The scene draws nothing
there: the whole area above the desk is one hole, and the caster's own
browser, captured in OBS, shows through it. Beneath it sits the full desk,
the same as metro's, so the race name and the clock stay on screen; the
clock, the scene's only live data, follows `delay` as on every race scene.

`delay` does not reach the page in the hole, though: it is the caster's own
browser, live. A race page shown there runs `delay` seconds ahead of the
delayed captures (a fog gate, a death or a finish on its leaderboard before
the viewer's video shows it), and its clock ahead of the desk's.

| Hole    | Label   | Position (x, y) | Size (w x h) |
| ------- | ------- | --------------- | ------------ |
| browser | BROWSER | 16, 16          | 1888 x 736   |

Plus the shared desk band.

The hole is much wider than 16:9 (about 2.6:1): it is meant for web pages,
which lay out at whatever size the window gives them, not for 16:9 video,
which would leave bars on both sides. Two ways to fill it in OBS:

- a Window Capture of the caster's own browser, the window sized so that the
  page area has the hole's proportions (1888 x 736 at 100% display scaling),
  and the tabs and address bar cropped off in OBS (Alt + drag on the
  source's edge, or the crop fields of its Edit Transform). The caster
  browses as usual and the stream follows; a window kept for the broadcast
  alone avoids putting another tab, or a logged-in view, on air.
- a second Browser Source at 1888 x 736, pointed at the page, under the
  scene's own, with its Custom CSS field cleared: OBS's default
  (`overflow: hidden`, a transparent background) stops the page from
  scrolling and can let what sits beneath show through it. No browser
  chrome to crop, but the caster can only browse through OBS's Interact
  window.

### Talk

An intermission or desk scene for a playoff evening: two caster cams,
centred and much larger than the desk band's, a topline naming the stage and
its date, the evening's three race slots (each a placeholder, a live race, or
a finished one), and the stage's running standings. It seats no runners and
carries no live race data of its own; it is pointed at an event stage rather
than at a race, via its own path
(`/overlay/cast/event/<slug>/<stage>/talk`).

This is the scene a broadcast typically opens on and returns to between
races, so it holds the frame longest before the stage's first race has a
result. Before then, the standings panel shows its title with a line of
muted copy underneath saying results arrive after the first race, rather
than an empty list under a title that would read as broken.

Having no WebSocket, the scene re-reads the event every 30 seconds, so the
race cards and the standings follow the evening while the source stays up
in OBS all night, with no reload from the caster. The standings count the
finished races only (`settled_results`), not the attached ones: races
created ahead of the evening do not count until they are over, and a race
still running, which scores provisionally on the event page (see the
Playoff scoring section of `EVENTS.md`) with every runner still on its
course on 0, would read as runners who scored nothing; the race card beside
it already follows the live race. The standings' eyebrow says how far to
trust them: "Provisional" while the stage is raced, "Complete" once its
last race is over, and nothing before the first result. It does not count the races
played, which the race cards beside it already show. A stage whose key
leaves the event's config mid-evening freezes the scene on its last copy
rather than blanking it on air; the URL has to follow the new key.

Each race card also shows the points that race itself gave, in the result
row's gold cell (on the talk scene a gold number is always a points value,
the same vocabulary as the standings' totals; the finisher's time sits
beside it in secondary). The server sends them per race (`races[].points`,
the same `score_playoff_race` scoring the stage totals sum): once a race
with a finisher is over, every row shows its points, a DNF's 0 included;
while it runs, only the settled finishers do, since everyone else's 0 is a
provisional DNF. A running race's card follows it: its whole field in the
race page's live order (the server's `races[].live`, finishers first by
in-game time, then the deepest layer; never capped, so a big field shows its
true top rows and "+ N more"), each runner still on the course at the depth
reached ("17/35") in the time cell, one yet to start blank. A runner out of
the race reads DNF or DQ there, during the race and after it.

While the stage is still being raced, the runners standing above its cut
(`advance`, the stage's own config) already wear the advancing mark, the
brass rule and the chip naming where their place goes on: the same
presentation as once the stage is complete, the "Provisional" eyebrow saying
it can still change. Once the stage is complete, the server's verdict
(`advances`) alone decides who carries it.

The same scene can point at one of the event's showcases instead (an
evening outside the bracket, see "Showcases" in [EVENTS.md](EVENTS.md)), at
the same path with the showcase's key in place of the stage's. The topline
then carries the showcase's label alone, without "Playoff night"; a race card
with no race yet lists the runners of the showcase's other races, since a
showcase declares no field; and no runner in its standings carries the
advancing mark, since nobody goes on from it.

Both the stage standings panel (`CastRoundStandings`) and each race card's
finisher list (`CastRaceCard`) cap their rows to what their own rect fits
(see "Field-size overflow" above); unlike the metro scene there is no
caster override here, since the stage's field size and a race's finisher
count aren't something a caster usefully chooses. The stage standings
panel's own row is 56px tall with a 36px avatar (down from the mockup's
72px/46px), measured against a real 10-runner stage where the original
size only fit 3 of them in the panel's 412px height; the brass chip and
the advancing runner's rule stay exactly as they were. The chip on each
advancing runner names the stage their place goes on to ("Quarter A" for a
group's winner, "Quarter C" for its runner-up when the places are crossed):
the talk page finds it as the stage whose seat takes that place.

| Hole  | Position (x, y) | Size (w x h) | Shown when  |
| ----- | --------------- | ------------ | ----------- |
| CAM 1 | 16, 76          | 736 x 552    | `cams >= 1` |
| CAM 2 | 1168, 76        | 736 x 552    | `cams >= 2` |

Panels: the topline at (16, 16), 1888 x 44; a lockup between the two cams at
(780, 76), 360 x 552; three race cards at (16, 652), (468, 652) and (920,
652), each 436 x 412; a 1px-wide separator at (1388, 652), 1 x 412; the stage
standings at (1420, 652), 484 x 412.

## URL parameters

Parsed by `parseCastParams` in `web/src/lib/cast/params.ts`, then handed to
each scene as `castParams`. Not every scene reads every one of them: quad
reads `p1`..`p4`, `cams`, `c1`, `c2`, `delay`, `guides` and `event`, but not
`focus`, since it has no single hero slot to pick. Focus reads all seven.
Metro reads `cams`, `c1`, `c2`, `delay`, `guides` and `event`, but neither
`p1`..`p4` nor `focus`: it has no POV holes to seat and no hero, so
`sceneLayout("metro", ...)` is called with `cams` alone and `resolveSlots` is
never called on that page at all. A `p1` or `focus` added to a metro URL is
silently ignored. Browser reads the same parameters as metro, for the same
reason: it seats no runner, and its `delay` only shifts the desk's clock.
Duel reads `p1` and `p2` (its only two holes; a `p3`, `p4` or `focus` in its
URL is silently ignored), plus `cams`, `c1`, `c2`, `delay`, `guides` and
`event`. Talk only reads `c1`, `c2`, `cams` and `guides` (it has no runners
to seat and no live feed to delay; see "Delay" below). Every scene but talk
also reads `follow` (see "Following a stage" below), which talk does not
need: it is keyed by its stage already.

A caster's name prints under their cam as the URL writes it, whether or not
they have an account here; the talk scene alone looks the name up and, when
it is a registered user's Twitch username, shows that user's display name
instead.

| Param      | Meaning                                                                                                                             | Default |
| ---------- | ----------------------------------------------------------------------------------------------------------------------------------- | ------- |
| `p1`..`p4` | Twitch username wanted in that POV hole, or `-` to keep this hole empty; a silent slot falls back to join order (see below)         | none    |
| `focus`    | Which slot (1 to 4) is the hero on the focus scene                                                                                  | 1       |
| `cams`     | How many caster cam holes to cut: 0, 1 or 2                                                                                         | 2       |
| `c1`, `c2` | The two casters' names shown under the cam holes                                                                                    | none    |
| `delay`    | Seconds to hold live updates back by, clamped to 0 to 60                                                                            | 0       |
| `guides`   | `1` draws the position guides over every hole                                                                                       | off     |
| `event`    | The event slug whose co-brand the lockup shows                                                                                      | none    |
| `follow`   | `<slug>:<stage>`: the event stage (or showcase) whose current race the scene moves to between races (see "Following a stage" below) | none    |

A named slot (`p1`..`p4`) seats that exact runner; a silent slot is filled
from the runners nobody named, in join order (`color_index` ascending, which
the server assigns as max + 1 on join, so it is join order by construction).
`resolveSlots` deliberately does not reseat a hole as the live leaderboard
reorders during the race: doing so would put the wrong runner's name over
someone else's video mid-race. A slot set to `-` (`EMPTY_SEAT`, `p<n>=-`)
keeps its hole empty: it matches nobody and the join-order fallback does not
refill it, so the hole stays part of the plate, like a name that matches
nobody in the race. It is how a URL says "nobody here" explicitly, where a
silent slot would seat whoever the fallback picks.

A stage-keyed URL may also carry `hold=<race id>`: it is internal, set by
the follow mode's fallback (see "Following a stage" below), never written by
a caster.

### What a built URL carries

`buildCastUrl` (`web/src/lib/cast/urls.ts`) is what the setup panel uses to
turn its form into a scene URL, and it does not carry every parameter every
time:

- The path names the race (`/overlay/cast/race/<id>/<scene>`), or, with
  `stageKeyed`, the event stage
  (`/overlay/cast/event/<slug>/<stage>/<scene>`, see "Following a stage"
  below); talk's always names its stage.
- `p1`..`p4` only for the slots actually named, `-` included (`p<n>=-`, a
  hole kept empty), and only on the scenes that seat runners: one per POV or
  hero hole the scene's layout cuts (`p1`..`p4` on quad and focus, `p1`..`p2`
  on duel, none on metro and browser).
- `focus` only on the focus scene, and only when set.
- `c1`/`c2` only for the casters actually named.
- `event` only when a co-brand is chosen, race scenes only.
- `cams` always, on every scene, whatever its value, even when it is the
  default of 2. `cams` changes which holes exist at all, so a saved or
  shared URL needs to say so explicitly rather than lean on a default that
  could change independently of the URL.
- `delay` only when it is not 0, race scenes only. A delay of 0 behaves
  exactly like no `delay` parameter at all (`parseCastParams` falls back to
  0 either way), so leaving it off the common no-delay case keeps that URL
  shorter without changing what it does.
- Never `follow`: a stage-keyed URL needs none, and its scene adds it itself
  when it hands over to a race.

## Following a stage

A playoff evening plays several races of one event stage (or showcase), and
a caster's OBS scenes should not need a new URL for each. The race scenes
therefore also exist keyed by the stage, siblings of the talk scene:
`/overlay/cast/event/<slug>/<stage>/<scene>` for quad, focus, duel, metro and
browser (`web/src/routes/overlay/cast/event/[slug]/[stage]/[scene=castRaceScene]/`),
with the same query parameters as the race scenes. Such a URL names no race
at all, so it survives a race being deleted, detached or recreated before
the evening.

**The current race** of a stage is the last race by slot index whose status
is running or finished; while none has started, the race with the lowest
index. The server answers it, with whether the stage is done (every one of
its races finished), at `GET /api/events/{slug}/stages/{key}/current-race`
(see the API section of [EVENTS.md](EVENTS.md)), a light endpoint unlike the
event detail. A race runs from the organizer's start command, so a scene
moves to the next race at the start of its countdown, never before it
starts; between two races, quad and metro still show the previous race's
final state, for the recap.

**The stage-keyed route** only resolves: it asks for the current race and
hands over to the same scene of that race,
`/overlay/cast/race/<current>/<scene>`, with the query string unchanged
plus `follow=<slug>:<stage>`, replacing the page's address rather than
adding a history entry. While the stage has no race at all, or the answer
does not come (server unreachable, an error, a stage key the event does not
know), it shows the **waiting plate**: the scene's opaque plate with no POV
hole pierced and nothing drawn on it (no desk; the cam holes, and the
browser scene's hole, stay cut), never an error page on air. It asks again
every 5 seconds and hands over as soon as a race exists.

**A race scene with `follow`** (`web/src/routes/overlay/cast/race/[id]/+layout.svelte`)
keeps following the stage named in its URL, never the shown race's own slot.
Every 5 seconds, and only while the race it shows is not running (still in
setup, or finished), it asks for the stage's current race; when that is
another race, it moves to the same scene of it, query string unchanged
(replacing the address again), and the layout loads that race and
reconnects its WebSocket. A running race is never polled for, and never
left: nothing can replace it before it ends. A failed answer only means
asking again 5 seconds later. Once the stage is done on the race shown,
polling stops for good. The status it goes by is the live one, `delay`
included, so a delayed scene starts asking once its own feed shows the race
over. The decision is one pure function, `followStep`
(`web/src/lib/cast/follow.ts`), shared by both routes.

After a hand-over the page's address is the race URL with `follow`, not the
stage-keyed URL: an OBS refresh reloads that race URL, which keeps following
the stage from there, and only a source given the stage-keyed URL again
resolves from scratch. When that race cannot load (the server unreachable
during the refresh, the race deleted), the scene does not show an error
page: the race layout falls back to the same scene's stage-keyed URL, query
kept, `follow` dropped and `hold=<that race>` added, so the waiting plate
takes over. While the stage still names the held race, that route does not
hand straight back to it (two routes bouncing on a race that will not
load); its poll retries the race 5 seconds later, and a race that still
fails falls back again, a 5-second retry with the plate up. A stage naming
another race hands over at once, as usual. `fallbackTarget`
(`web/src/lib/cast/follow.ts`) builds that URL, `followTarget` drops `hold`
from the race URL it builds.

The talk scene already follows its stage on its own (it re-reads the event,
see Talk) and takes no `follow`.

## Wielded weapons

The duel runner cards and the focus scene's hero card name the weapons
their runner is wielding right now ("Moonveil + Misericorde"), without the
upgrade level: competitive modes play at max upgrade, so it would be
noise. The quad cards don't: their height budget has no room a weapon
line could take at a size legible on a broadcast (it measured 13px mono
and was ruled illegible on a real race). The mod reports the equipped hands in every status_update
(it always has; the server counts them per zone in `zone_history`, the
combo counters the race page's weapons popover aggregates), and the server
now relays the observed combo on that runner's `player_update`, so the
line follows a swap within a tick (see the `player_update` section of
`PROTOCOL.md`). A tick that observed nothing (loading screen) carries no
combo rather than "unarmed", so the last known combo stands. A page that
just connected seeds from the current zone's most-used combo
(`zoneTopCombo` in `web/src/lib/weapons.ts`) until the first live tick; a
runner whose mod is disconnected, or who has finished, keeps the last
combo observed. Names resolve through the `GET /api/weapons` catalogue;
until it loads (retried while the scene is up), the line stays blank
rather than printing a raw id.

## Delay

The race's live data (leaderboard, zone updates, race status, the clock)
reaches a cast scene over the same WebSocket the race page itself uses,
essentially instantly. A caster's own Twitch POV capture does not: between
the runner's game, their own encode, and the platform's ingest and playback,
a captured stream commonly runs several seconds behind the live game. Without
a delay, the standings overlay would announce a fog gate, a death, or a
finish before the viewer's video shows it happening, spoiling the reveal the
broadcast is built around.

`delay` (seconds, clamped to 60) becomes the `delayMs` passed to
`raceStore.connect`, which holds every incoming update back by that many
milliseconds before applying it (`web/src/lib/cast/delay.ts`): a `setTimeout`
per message, so messages sent in order still apply in order. The scene's own
clock (`CastDesk`) reads the same delay from the URL directly, so the
elapsed time and the countdown it shows always match what the delayed video
is showing, not the server's real time. Talk carries no `delay` parameter:
it holds no live feed, only the event it re-reads every 30 seconds, and it
is meant for between races. A race ending while it is on air can therefore
show there (a finisher's time on its card, the standings reordering) before
a delayed capture does. The browser scene delays its desk's clock, but not
the page in its hole: that is the caster's own browser, live (see Browser).

## The setup panel

`CastSetup.svelte` is a panel on the race page (`/race/[id]`), opened with
the "Cast Setup" button, or automatically by adding `?cast=1` to the race
page's own URL. Only the race's casters see the button, and `?cast=1` opens
the panel only for them: the race's organizer does not, unless they cast it
too.

It gives a caster, without hand-editing a URL:

- A live preview of the currently selected scene, scaled down, connected to
  the race over its own WebSocket. The preview's own URL settles about half a
  second after the panel's inputs stop changing, so typing a runner or
  caster name doesn't reload the preview (and reopen its spectator
  WebSocket) on every keystroke; every other field in the panel stays live.
- A scene picker: Quad, Focus 1 through 4, Duel, Metro, Browser, Talk.
- Hole assignment, on the scenes that seat runners (quad, focus, duel): a
  dropdown per POV hole (two on the duel scene), every one starting on auto,
  so the URL carries no `p<n>` and the scene seats the live field (a field
  still forming when the panel first opens is not frozen into it); the
  caster picks a runner only to override a hole. Each auto option names the
  runner the scene would seat there ("(auto: alice)", "(auto: nobody)" past
  the field), worked out by the scenes' own `resolveSlots`. Picking one
  takes that runner out of the join-order pool, so the auto holes after it
  shift (on a field of five, the fifth picked in POV 2 moves the second and
  third to POV 3 and 4), and their options say so: a caster who needs a
  seat to hold picks it too. The panel leaves hole assignment out on metro,
  browser and talk, keeping the seats picked for the next scene that has
  some. Picking the
  same runner twice is refused rather than silently hiding another runner,
  except when the duplicate sits in a hole the duel scene doesn't render,
  which is freed instead (it can't be cleared from the panel).
- Cams (0, 1 or 2) and the two caster usernames.
- An event co-brand picker, and, on the talk scene, a stage picker scoped to
  the chosen event: its stages, then its showcases. A race attached to an
  event starts from that event as its co-brand (the race detail's
  `event_slug`), and from the stage or showcase its slot names (`<key>:<n>`)
  as the talk scene's stage, so "Copy all scene URLs" carries the talk URL
  from the start; a qualifier race starts from its event alone, talk
  introducing playoff evenings. The picker lists the events on the bill plus
  the race's own, so a race of an older season still names it. The scenes
  themselves never fall back to the race's event: a URL with no `event`
  shows no co-brand.
- Delay in seconds (race scenes only).
- The built URL for the current scene, with a copy button, and a "Copy all
  scene URLs" button that copies every race scene's URL plus talk's once an
  event and stage are both chosen. Selecting the talk scene before then
  withholds the preview, the URL and its copy button, and the "Open with
  position guides" link below, each replaced with a hint to pick an event
  and stage first: none of the three are valid URLs yet (an unconfigured
  talk URL would only point at a 404).
- Next to it, two buttons that download a ready-to-import OBS scene
  collection (see "The OBS scene collection" below), built in the browser
  from the panel as it stands: its co-brand, casters, cams, delay and
  pinned seats.
  - **"Download OBS scenes"**: the collection for this race, its scenes
    named by the race (`/overlay/cast/race/<id>/<scene>`). Its seats are
    the race's runners, exactly as the hole dropdowns' "(auto: ...)"
    options name them (`raceSeats` in `web/src/lib/cast/obs-export.ts`).
    It opens on talk under the same rule as "Copy all scene URLs" (an
    event and a stage both chosen, the talk picker's), else on quad. The
    file is `speedfog-<event>-<stage>-<n>.json` for a race in a stage or
    showcase slot, else `speedfog-race-<first 8 characters of its id>.json`.
  - **"Download OBS scenes for the match"**: the collection for the whole
    evening, on a race in a stage or showcase slot, once the race's own
    event detail has loaded (the panel asks for it once, whatever the
    co-brand and talk pickers say). Its race scenes are keyed by the
    race's own stage, never the talk picker's
    (`/overlay/cast/event/<slug>/<stage>/<scene>`, see "Following a stage"
    above), so they follow its current race on their own and the file
    names no race. It always opens on that stage's talk scene. On a stage,
    its seats are the stage's declared field (`stage.field` in the event
    detail), in field order, with the panel's pins on top (`stageSeats`):
    the field is the same for every race of the stage and known before any
    race has runners, so the file is identical whichever race of the match
    it is downloaded from. A seat whose runner is not known yet (a fed
    seat whose source stage is not over) seats nobody, and so does a
    forfeited one (its runner races none of the stage's races); until
    every seat has its runner, a hint under the button says "The match's
    field is not settled yet: seats without a runner stay empty." A
    showcase declares no field, so the race the file is downloaded from
    supplies the runners, as for the race file: a showcase whose races
    seat different runners needs a race file per race. The file is
    `speedfog-<event>-<stage>.json`.
- An "OBS positions" table: every hole of the current scene's label,
  position and size (the same `formatGeo` line the guides mode prints), minus
  the metro scene's map, which is never a video source (see "Composition
  model" above), plus a link that opens the same scene with `guides=1`.

Settings are kept per race in `localStorage` under `cast-setup:<raceId>`, so
reopening the panel for the same race remembers the last setup; a private
window that refuses storage just does not persist between visits. What is
saved wins over the prefill from the race's event, a cleared co-brand
included: a race attached to its event after its panel was first opened
keeps the setup it had then.

A stage's races share their settings instead, so the match file does not
differ from one race's panel to the next. Once the race's own event detail
shows its slot is a stage, the panel moves to the stage's entry,
`cast-setup:stage:<event slug>:<stage key>`, once: it adopts what an
earlier race of the stage saved there, or else seeds it with its own
settings (loaded from `cast-setup:<raceId>` until then); every change from
then on is saved there. Every setting is stage-wide (seats by username,
cams, casters, delay, co-brand, talk stage): a stage's field is fixed. A
showcase, and any race in no stage slot, keeps `cast-setup:<raceId>`: a
showcase's races may seat different runners, and a pin carried to a race
its runner is absent from would leave that hole empty.

## The OBS scene collection

The setup panel's two download buttons (see "The setup panel" above) write
an OBS scene collection, a JSON file OBS imports with Scene Collection >
Import, built by `buildObsCollection` (`web/src/lib/cast/obs.ts`). Its
scenes, in this order, the first being the one OBS opens on:

1. **Talk**: always on the match file; on the race file once the panel has
   an event and a stage chosen.
2. **Quad**.
3. **Focus: <runner>**, one per seated runner in slot order, that runner the
   hero.
4. **Duel: <runner> vs <runner>**, one per pair of seated runners in slot
   order (1-2, 1-3, 1-4, 2-3, 2-4, 3-4) when the field has at most four
   runners; above four, only the pair seated in POV 1 and 2.
5. **Metro**.
6. **Browser**.
7. The placeholder scenes: **Cam 1** and **Cam 2** (as many as `cams`), then
   **Audio**.

Scene and source names carry the runner's display name, or every runner's
Twitch login when two display names would read the same (OBS wants every
name unique). The collection is named "SpeedFog · <race name>", or
"SpeedFog · <event name> · <stage label>" for a match.

**Every seat is written out.** Each plate URL names every seat, the auto
ones included: the runner's username, or `-` (`p<n>=-`, see "URL
parameters") for a seat nobody fills. The plate's cards and the source
under each hole therefore always agree, on every race of the evening, and
a runner who joins after the download is never seated over a hole with no
source under it. A caster downloads the file again once the field changes.

**In each cast scene**, from the top:

- the plate: a Browser Source at 1920x1080 on the scene's URL
  (`buildCastUrl`, from the panel's settings), muted and hidden from the
  audio mixer;
- one source per hole the plate pierces for the seated field
  (`pierceableHoles`: a quad on a three-runner race gets nothing under
  POV 4, and the metro map, never a hole, gets nothing): the runner's POV
  under a POV or hero hole, the Cam 1 or Cam 2 scene under a cam hole,
  "Browser capture" under the browser scene's hole;
- the Audio scene, nested at the bottom.

**POVs** are Browser Sources on Twitch's popout player
(`https://player.twitch.tv/?channel=<login>&parent=twitch.tv&player=popout`),
one per runner, shared by every scene showing them (OBS loads a shared
source once). Their audio goes through OBS: they start muted, but stay in
the mixer under OBS's control, so a caster can unmute one runner on
purpose, and a muted runner stays silent.

**Placeholders** stand in for what only the caster can provide, filled once
after the import:

- **Cam 1** and **Cam 2**: empty nested scenes. The caster adds their webcam
  (or the co-caster's Discord capture) inside once, and every scene with
  that cam hole follows.
- **Browser capture**: a Window Capture with no window chosen. The caster
  picks their browser window and crops its tabs and address bar off (see
  Browser).
- **Audio**: a nested scene holding a microphone, "Mic" (the default input
  device), and two application audio captures with no application chosen,
  "Discord" and "Music".

The window capture, the microphone and the application audio captures are
Windows source types (`window_capture`, `wasapi_input_capture`,
`wasapi_process_output_capture`). On macOS or Linux they load as missing
sources, which the caster replaces with their platform's own.

**Placement.** Every source sits in a bounding box equal to its hole's rect
(`sceneLayout`, the rects the plate cuts), scaled to cover the box (OBS's
"Scale to outer bounds") and cropped to it, top-left aligned: any source
fills its hole exactly, whatever its own resolution or aspect ratio (a 720p
stream, a 4:3 webcam inside a 16:9 nested scene). OBS reads that crop since
30.1; an older one ignores it, and the overflow stays under the opaque
plate. Positions are written both ways, as OBS saves them: in canvas pixels
for OBS up to 30, and relative to the canvas for OBS 31+, which then keeps
the layout on any 16:9 canvas (1280x720, 2560x1440). Every item is locked,
so a stray drag cannot move a source off its hole.

## Setting up in OBS

1. On the race page, as one of its casters, open Cast Setup.
2. Set `cams`, name the casters, optionally pin specific runners into POV
   holes, and optionally pick an event co-brand (and talk's stage), both
   already filled in on a race attached to an event. Set the delay to
   roughly how far behind live your own capture runs.
3. Download the collection: "Download OBS scenes for the match" for a
   playoff evening (one file serves all of its races), else "Download OBS
   scenes".
4. In OBS, Scene Collection > Import: add the file, import it, then switch
   to the new collection from the Scene Collection menu.
5. Fill the placeholders once: your webcam (and the co-caster's capture)
   inside the Cam 1 and Cam 2 scenes, your browser window in "Browser
   capture", your microphone and the Discord and music applications in the
   Audio scene's sources (on macOS or Linux, your platform's own sources in
   their place).
6. Switch between the scenes in OBS as commentary moves between the talk
   desk, the quad view, a focused runner, a duel, the map, or a web page.
   A match file's race scenes move to the stage's next race on their own;
   download again once the field changes (and a race file for each race).

### By hand

Without the import (another tool than OBS, or a single cast scene added to
a collection of your own), build each scene yourself:

1. In Cast Setup, pick a scene and set it up as in step 2 above; leave
   talk's delay alone, it has none.
2. In OBS, create a new Scene for this cast scene.
3. Add the video sources it needs (webcam captures for the cam holes,
   captured Twitch POVs for the runner holes, a capture of your own browser
   for the browser scene's hole) anywhere in the scene, below where the
   Browser Source will sit in the source list.
4. Open the setup panel's "Open with position guides" link (or add
   `guides=1` to the scene URL yourself) in a browser window, and resize or
   reposition each video source in OBS until it lines up with its outline
   (or give it the hole's position and size, from the panel's "OBS
   positions", as a bounding box in its Edit Transform).
5. Add a Browser Source at exactly 1920x1080, pointed at the plain scene URL
   from the "Copy" button (no `guides=1`), and place it above every video
   source in the scene's source list: it paints the opaque plate everywhere
   except the holes, so only the sources sitting under a hole show through.
6. Repeat steps 2 to 5 for each additional cast scene the broadcast needs,
   as its own OBS Scene.
