# Layer Comparison

Under the map of the race page (`/race/[id]`) and the daily page
(`/daily/[date]`), selecting two or more runners in the leaderboard opens a
comparison of their runs, layer by layer: a gap chart aligned on the map's
layer columns, and a detail panel for one layer. It answers "where did I
lose time against this runner, and why": a slower branch, or a slower
execution of the same zone.

The interface calls a layer a **depth**, numbered from 1 like the node
popup and the leaderboard; this doc and the code keep the graph's "layer"
(`graph_json`'s `layer`, 0-based).

## Where it shows

`MetroDagFull` renders it behind the opt-in `layerGaps` prop, which both
pages pass in the Map view only (Replay has its own timeline). It appears
wherever the full map already shows with highlights: a finished participant
while the race still runs, spectators under the map's visibility rules, and
finished races. With a single runner selected, a hint under the map invites
the viewer to select another. Overlays and cast scenes never pass the prop,
and follow mode ignores it.

Everything is derived on the client from data the full map already receives
(`graph_json`, every participant's `zone_history`, status and IGT), so the
comparison exposes nothing the map does not.

## Conventions

The computation lives in `web/src/lib/layer-gaps.ts` (pure, unit-tested).
Every DAG edge goes from layer L to layer L+1, so every runner crosses every
layer and the per-layer view is always defined.

- **Arrival** on a layer: the IGT of the runner's first history entry on a
  node of that layer. Revisits never create a second arrival (the same
  convention as the DNF ranking, see "Leaderboard Sorting" in
  `RACE_LIFECYCLE.md`).
- **Node taken**: the node the runner left the layer through, i.e. its last
  entry on that layer before arriving on the next one (the "cleared" notion
  of the zone stats in `STATS.md`). While the layer is still open, the
  latest node.
- **Time on a layer**: the next layer's arrival (the finish IGT for the last
  layer) minus this one. A detour counts on the layer where it happened.
- **Back-out**: when the node taken differs from the first node entered on
  the layer (the runner warped back and took another branch; about half the
  runners do it at least once per race). The detour runs from the layer's
  arrival to the first entry on the node taken.
- **Time through the node**: the next layer's arrival minus the first entry
  on the node taken. Equal to the time on the layer for a direct traversal;
  the post-detour part otherwise. This is what the field reference compares.
- **Deaths** of a layer: those of the entries recorded between its arrival
  and the next layer's, whatever layer their node belongs to. A death during
  a detour lands on the layer where the time was lost.
- **Gap**: a runner's arrival minus the earliest arrival of the selected
  runners who reached that layer.
- **vs best**: time on the layer minus the shortest one in the selection,
  all nodes together.
- **Field reference** of a node: best, median and count of the time through
  the node of every participant of the race who left a layer through it.
  Disqualified participants are left out, so a cheat never sets the
  reference. A runner's field rank is 1 + the number of strictly faster
  samples.
- **Runner state on a layer**: done (left it), live (still on it, playing:
  time so far, no comparison), out (abandoned or disqualified on it: "DNF" or
  "DQ"), unknown (left it or finished, but the history missed when: "-").
- **Display**: gaps use the leaderboard's compact format (`+M:SS` under ten
  minutes, then `+Mm`, then `+HhMM`).
- **Inconsistent histories** (a layer first recorded after the next one, or
  missing): that layer is skipped for the runner, the line joins the
  neighbouring points, and the layer before it gets no time.
- **Rolled-back IGT** (a backup restore sets the clock back): a time that
  would come out negative is unknown ("-"), never a record, and a back-out
  whose detour would be negative is named without its duration.

## Chart

- x comes from the map's layout. A layer's entry sits on its fog gate,
  halfway between its column and the previous one; the start half a column
  before layer 0, the finish half a column after the last layer. The
  segment right under a node is therefore the time spent on that layer.
- y is linear from the top (0, the first of the selection) to the largest
  gap rounded up to a 1, 2, 5, 10, 20, 30 or 60 minute step (five intervals
  at most, one minute minimum).
- One line per selected runner in their player line color. Deaths show as
  the charter skull on the layer's segment (count beside it above one). A
  runner out of the race ends on a terminus bar; a playing runner's line
  stops at the entry of its current layer.
- The chart follows the map's horizontal pan and zoom. `ZoomableSvg` binds
  out its view: `zoom` and `panX`, plus how it renders layout units,
  `viewScale` (pixels per unit, measured on its own svg) and `viewOriginX`
  (where content x = 0 sits from its container's left edge, its centered
  crop included). The chart is exactly as wide as the map's container and
  places x with these, so it never copies the map's box rules (600px
  minimum, centering, crop): a phone crops the map, never the chart, whose
  y labels stay at its left edge. Column x comes from the layout itself
  (`DagLayout.layerX`). The chart does not capture the mouse wheel, so it
  never traps the page scroll: zoom on the map.

## Interactions

Hovering a column highlights it in fog, draws a fog guide on the map at the
same layer and fills the detail panel. Two pieces of state drive it in
`MetroDagFull`: the shown layer and the pinned one. The panel stays hidden
until the first hover of a comparison; after that, leaving the chart keeps
the last hovered layer on show (with its band and map guide), so it never
empties under the reader and the pointer can reach it. A click, a tap or an
arrow key pins a layer and shows it; the pointer can then explore other
columns, and leaving the chart brings the pin back. A second click or
Escape releases it and keeps it on show. Closing the comparison resets both.
With the chart focused, Left and Right move the pinned layer. Keys go
through `chartKey`; the chart calls `preventDefault` on the ones it
handles, and the leaderboard's window-wide Escape (which clears the
selection) ignores a prevented event, so releasing a pin takes one press
and clearing the selection a second. A node name in the panel opens the
map's node popup.

## Detail panel

One column per node the selection left the layer through, the fastest node
first: as many columns as nodes up to three (one or two nodes span the whole
width; a fourth, only possible on old seeds, wraps to a second row), and a
single column when the panel is narrower than 36rem.
The widths come from container queries on the panel, not the viewport: with
the chat open, the main column is far narrower than the screen. A runner row
fits on one line when its node column is at least 21rem wide, and wraps onto
two lines otherwise.

## Performance

`raceStore` delivers a `player_update` about every second per playing
runner. The comparison reads the map's own narrowed copy of the
participants (`pathParticipants`, which also compares status and a
non-playing runner's IGT, i.e. a finish time), so live ticks rebuild
nothing. When it does change,
`buildTimelines` hands back each runner's previous timeline while that
runner's history array (replaced, never edited in place), status and finish
time hold, so one runner's new zone rebuilds one timeline. The panel reads
the ticking participants only while it shows a playing runner's current
depth, for that runner's time so far. Pan and zoom move the lines through
one SVG group transform, and only reposition the death skulls and axis
labels.
