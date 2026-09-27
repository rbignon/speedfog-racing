# Cast Overlays

Four full-screen OBS scenes for a caster running a broadcast: quad, focus,
metro and talk. They are a different kind of overlay from the two existing
ones, `/overlay/race/[id]/dag` and `/overlay/race/[id]/leaderboard`: those are
transparent widgets a caster places anywhere on a scene they build themselves
(a DAG in one corner, a leaderboard strip along an edge, sized and positioned
by hand in OBS). A cast scene owns the whole 1920x1080 frame instead. It
paints an opaque plate over the entire canvas, cuts holes out of that plate at
fixed positions, and leaves those holes for the caster's own video sources
(webcams, captured Twitch POVs) to show through from underneath. The browser
source is the top layer of the OBS scene; everything else sits below it.

## Composition model

Each scene renders at a fixed 1920x1080 design canvas (`CANVAS` in
`web/src/lib/cast/layout.ts`), scaled down by the page itself to whatever
size the browser window or OBS Browser Source actually gives it, so the
Browser Source should always be added at 1920x1080 to avoid a second, OBS-side
rescale on top of the page's own.

The canvas has two kinds of content:

- **Holes** (`CastRect`, one of the roles `pov`, `hero`, `cam`, or `map`): a
  rectangle the plate does not paint over. An SVG mask (`maskDataUri`) cuts
  these out of the opaque plate, so whatever OBS source sits directly beneath
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
its outline, then drop `guides=1` for the real broadcast.

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

## The four scenes

Three of the four scenes (quad, focus, metro) share a **desk** band along the
bottom: a race name panel, a caster lockup (the SpeedFog Racing wordmark,
crossed with the event's co-brand when one is set), a clock panel, and up to
two caster cam holes. How many cam holes it cuts depends on the `cams`
parameter (0, 1 or 2); with 0, the desk still draws its race/lockup/clock
panels but pierces no cam holes at all.

| Hole  | Position (x, y) | Size (w x h) | Shown when  |
| ----- | --------------- | ------------ | ----------- |
| CAM 1 | 408, 776        | 384 x 288    | `cams >= 1` |
| CAM 2 | 1128, 776       | 384 x 288    | `cams >= 2` |

The desk's own panels (not holes, no OBS source needed): the race-name panel
at (16, 776), 376 x 288; the lockup at (820, 776), 280 x 288; the clock panel
at (1528, 776), 376 x 288.

### Quad

Four runners in a 2x2 grid, filling the main area above the desk. Each POV
hole has a runner card beside it (avatar, name, rank, layer progress); the
right column's cards are mirrored to face inward, toward their POV.

| Hole | Label | Position (x, y) | Size (w x h) |
| ---- | ----- | --------------- | ------------ |
| pov1 | POV 1 | 312, 16         | 640 x 360    |
| pov2 | POV 2 | 968, 16         | 640 x 360    |
| pov3 | POV 3 | 312, 392        | 640 x 360    |
| pov4 | POV 4 | 968, 392        | 640 x 360    |

Plus the shared desk band (cam holes as above).

### Focus

One runner large (the "hero"), the other three stacked small on the right,
for commentary that has settled on a single runner without losing sight of
the field. Which POV slot (1 to 4) becomes the hero is the `focus` parameter;
its own zone splits render beside it.

| Hole                     | Label              | Position (x, y) | Size (w x h) |
| ------------------------ | ------------------ | --------------- | ------------ |
| hero                     | HERO (POV `focus`) | 16, 16          | 1296 x 729   |
| pov (1st remaining slot) | POV n              | 1584, 16        | 320 x 180    |
| pov (2nd remaining slot) | POV n              | 1584, 212       | 320 x 180    |
| pov (3rd remaining slot) | POV n              | 1584, 408       | 320 x 180    |

The three small POV holes are whichever slots `focus` did not pick, in slot
order. A mini standings panel sits at (1584, 604), 320 x 148 (rank, colour
dot, name and gap; no depth cell, since the scene's own POVs already show
what each runner is doing), and the hero's own runner card fills the panel
at (1328, 16), 240 x 736. Plus the shared desk band.

### Metro

The seed's whole zone graph, drawn live, with a log of recent zone entries
and a full standings panel beneath. The map itself is not a hole: it is
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

The map shows the whole seed at once, start on the left and final on the
right, so a viewer reads at a glance how far into the race each runner is.
A seed is far wider than the box is tall (a 35-layer Boss Rush is about 7:1,
the box under 4:1), so the graph grows taller to fill it (MetroDagFull's
`fillContainer`, through `stretchToAspect` in `web/src/lib/dag/layout.ts`):
the space between its top and bottom rows spreads by up to
`FILL_MAX_ROW_STRETCH` (1.4, past which diagonals turn steep and the graph
looks squeezed), and the rest of the height becomes equal free bands above
and below, where the runners' names go. Zone names are left out: at this
zoom they would render at a few pixels, and the standings below already name
each runner's zone. The runners' marks (tags, trails, death skulls) keep the
size they have at a 13-layer window however far the map zooms out, and the
nodes and edges grow partway (by the square root of the zoom-out), enough to
stay visible without crowding (MetroDagFull's `keepMarkSize`, with
`MARK_REFERENCE_WIDTH`).

Each runner on the map is a tag, as the reference mockup draws it
(`.mt-dot`, `.mt-line`, `.mt-name`): a still dot in a dark ring with a halo
in the runner's colour, a straight vertical connector, and the name in large
type at its end (`LivePlayerDots`' `playerTags`, instead of the orbiting
dots the race page shows). Runners on the same node sit side by side; before
the start the field gathers on the start node, and finishers on the final
node, past anyone still fighting there. A crowd at an edge of the map slides
inward as a whole. On the whole map, names go in the free bands, their
connectors reaching past the graph's outer rows (and past the node glyphs
there), and the free slot with the shortest connector wins: names stack in
the band nearer their dot until crossing to the other band is shorter. Each
dot keeps the stretch between itself and its own name free of other names,
so a name never lands between a dot and that dot's own name on the same
vertical; only when both bands are full does a name fall back over the graph
(`placeTags`' lanes, in `web/src/lib/dag/tags.ts`). In the follow view, with
no bands, each name points toward the middle of the window instead, where
there is room, and a name that would cover another name or another runner's
dot tries the other side, then one tier further out. A runner on the middle
row keeps a side of their own (from their colour slot), so a tag doesn't
flip because someone else moved. Names stay inside the window the viewport
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
of showing the whole seed, and brings the zone names back; `labels=0` or
`labels=1` forces the zone names off or on either way; `fontSize` sets their
size (default 9, down from the plain `/dag` strip's 11: measured against 7,
which read thin at broadcast distance, and against 11, which made a 90-node
seed illegible).

The standings panel beneath the map is a single column, one row per runner
as the mockup draws it: rank, colour dot, name, zone, deaths, depth and gap.
A playoff race seats four runners, which is exactly what the panel fits; a
bigger field gets the row cap described in "Field-size overflow" above. It
also reads a `lines` query parameter (default: fit as many rows as the panel
allows), the same name and spirit as `/overlay/race/[id]/leaderboard`'s own
`lines`, letting the caster show fewer rows for a field they'd rather keep
short. It cannot ask for more rows than the panel actually fits.

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
in OBS all night, with no reload from the caster. The standings' "After N
of M races" eyebrow counts the finished races, as the event page's evening
section does ("N of M races played"), not the attached ones: races created ahead of the evening do not
count until they are over. A race still running adds the provisional
points of its runners already finished to the standings without moving that
count (see the Playoff scoring section of `EVENTS.md`). A stage whose key leaves
the event's config mid-evening freezes the scene on its last copy rather
than blanking it on air; the URL has to follow the new key.

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
size only fit 3 of them in the panel's 412px height; the brass `Final`
chip and the advancing runner's rule stay exactly as they were.

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
silently ignored. Talk only reads `c1`, `c2`, `cams` and `guides` (it has no
runners to seat and no live feed to delay; see "Delay" below).

| Param      | Meaning                                                                                     | Default |
| ---------- | ------------------------------------------------------------------------------------------- | ------- |
| `p1`..`p4` | Twitch username wanted in that POV hole; a silent slot falls back to join order (see below) | none    |
| `focus`    | Which slot (1 to 4) is the hero on the focus scene                                          | 1       |
| `cams`     | How many caster cam holes to cut: 0, 1 or 2                                                 | 2       |
| `c1`, `c2` | The two caster usernames shown under the cam holes                                          | none    |
| `delay`    | Seconds to hold live updates back by, clamped to 0 to 60                                    | 0       |
| `guides`   | `1` draws the position guides over every hole                                               | off     |
| `event`    | The event slug whose co-brand the lockup shows                                              | none    |

A named slot (`p1`..`p4`) seats that exact runner; a silent slot is filled
from the runners nobody named, in join order (`color_index` ascending, which
the server assigns as max + 1 on join, so it is join order by construction).
`resolveSlots` deliberately does not reseat a hole as the live leaderboard
reorders during the race: doing so would put the wrong runner's name over
someone else's video mid-race.

### What a built URL carries

`buildCastUrl` (`web/src/lib/cast/urls.ts`) is what the setup panel uses to
turn its form into a scene URL, and it does not carry every parameter every
time:

- `p1`..`p4` only for the slots actually named, race scenes only.
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
a delayed capture does.

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
- A scene picker: Quad, Focus 1 through 4, Metro, Talk.
- Hole assignment (race scenes only): a dropdown per POV hole, defaulting to
  "(auto, join order)"; picking the same runner twice is refused rather than
  silently hiding another runner.
- Cams (0, 1 or 2) and the two caster usernames.
- An event co-brand picker, and, on the talk scene, a stage picker scoped to
  the chosen event: its stages, then its showcases.
- Delay in seconds (race scenes only).
- The built URL for the current scene, with a copy button, and a "Copy all
  scene URLs" button that copies every race scene's URL plus talk's once an
  event and stage are both chosen. Selecting the talk scene before then
  withholds the preview, the URL and its copy button, and the "Open with
  position guides" link below, each replaced with a hint to pick an event
  and stage first: none of the three are valid URLs yet (an unconfigured
  talk URL would only point at a 404).
- An "OBS positions" table: every hole of the current scene's label,
  position and size (the same `formatGeo` line the guides mode prints), minus
  the metro scene's map, which is never a video source (see "Composition
  model" above), plus a link that opens the same scene with `guides=1`.

Settings are kept per race in `localStorage` under `cast-setup:<raceId>`, so
reopening the panel for the same race remembers the last setup; a private
window that refuses storage just does not persist between visits.

## Setting up in OBS

1. On the race page, as one of its casters, open Cast Setup.
2. Pick a scene, set `cams`, optionally pin specific runners into POV holes,
   name the casters, and optionally pick an event co-brand (and, for talk, a
   stage). Set the delay to roughly how far behind live your own capture
   runs; leave talk's alone, it has none.
3. In OBS, create a new Scene for this cast scene.
4. Add the video sources it needs (webcam captures for the cam holes,
   captured Twitch POVs for the runner holes) anywhere in the scene, below
   where the Browser Source will sit in the source list.
5. Open the setup panel's "Open with position guides" link (or add
   `guides=1` to the scene URL yourself) in a browser window, and resize or
   reposition each video source in OBS until it lines up with its outline.
6. Add a Browser Source at exactly 1920x1080, pointed at the plain scene URL
   from the "Copy" button (no `guides=1`), and place it above every video
   source in the scene's source list: it paints the opaque plate everywhere
   except the holes, so only the sources sitting under a hole show through.
7. Repeat steps 3 to 6 for each additional cast scene the broadcast needs,
   as its own OBS Scene; switch between them in OBS as commentary moves
   between the quad view, a focused runner, the map, or the talk desk.
