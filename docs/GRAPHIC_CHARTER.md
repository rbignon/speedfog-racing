# SpeedFog Racing - Graphic Charter

## Design Direction

**"Timetable of the Lands Between"**: the fog-gate network is the identity. The metro-map DAG is not an illustration on top of the product, it _is_ the product, so its vocabulary (lines, stations, terminals) carries structure and status everywhere, and the typography speaks public-transit signage and race timing boards.

The sobriety discipline of the previous charter survives intact: the dark theme does the heavy lifting, gold appears sparingly as punctuation on high-value elements, flat design with subtle depth (fine borders, soft glows on active elements only). No gradients, no blur, no background textures, outside the two documented exception zones (Rage Quit button, name templates).

What changed versus charter v1, in one list:

- Inter is replaced by **Barlow Condensed** for display and **Public Sans** for UI text (a grotesque from the same public-signage world, drawn for interface sizes where Barlow's single optical size turned mushy), plus **Spline Sans Mono** for data. Three faces, three roles.
- The violet-500 secondary becomes **fog** (`#A99BC9`), and every semantic color leaves the Tailwind default palette for a hue tuned to the navy/brass world.
- Cards drop the 8px radius, the colored left border and the pill status chip for a near-sharp plate carrying a **route line** on its top edge.
- Section headers use the **station-and-line device** instead of free-floating letterspaced caps.
- Ranks, times, seeds, deltas and dates all run through the mono face.
- Emoji leave the chrome: medals become typographic `1st / 2nd / 3rd`, the skull becomes the dagger `†`, "Abandoned" in data rows becomes `DNF`.
- Per-participant **player line colors** thread the results rail, map traces, finish board and chat dots. They never color the player's name itself, which belongs to the equipped name template (see `REWARDS.md`).

---

## Color Palette

### Foundations (~90% of surface area, unchanged)

| Role             | Color                     | Hex       |
| ---------------- | ------------------------- | --------- |
| Background       | Deep blue-black           | `#0F1923` |
| Surface          | Very dark blue-grey       | `#162032` |
| Surface elevated | Blue-grey (hover, modals) | `#1C2A3F` |
| Border           | Subtle blue-grey          | `#253550` |

**Layering rule.** Background is the page ground. Surface is anything that holds content: fixed regions (the hero band, the race-page rails and chat sidebar) as well as plates (cards, panels, tables). Elevated is transient only (hover states, menus, modals, popups). Large regions are never flattened onto the page ground; a hairline border alone is not enough to give a rail its spatial identity.

### Accents

| Role               | Color            | Hex       |
| ------------------ | ---------------- | --------- |
| Brass (primary)    | Warm amber gold  | `#C8A44E` |
| Brass (hover/glow) | Light amber      | `#DDB95F` |
| Fog (secondary)    | Misty heliotrope | `#A99BC9` |
| Fog (hover)        | Light heliotrope | `#C0B4DC` |

**Brass usage (exhaustive list):** the "Racing" half of the wordmark, section header device + title, primary CTA button, the hero underline's and the DAG's start/terminal markers, the week line's playing-state segment and dot, the route lines' riding segment, position dot and boarded ring (the viewer's own run), the `Participating` role mark's square, 1st-place markers (`1st` labels, finish board place tags), the amber "running" daily strip. Nowhere else. (The week line's own edge markers and the finish board's terminal squares are state- or player-colored, not brass.)

**Fog usage:** interactive hover states (secondary buttons), links, focus rings, boss diamonds on the DAG, the `Organizing` role mark's diamond, radio/checkbox checked states (outside player-colored contexts). Route-line cards are the exception: they hover in their own line's status hue, not fog.

### Text

| Role      | Color            | Hex       |
| --------- | ---------------- | --------- |
| Primary   | Off-white        | `#E8E6E1` |
| Secondary | Blue-tinted grey | `#96A0AD` |
| Disabled  | Slate grey       | `#77808C` |

Disabled grey is for genuinely disabled or decorative elements only. Informational data (timestamps, deltas, dates, meta rows) never drops below secondary: on surface, disabled grey sits at the 4:1 contrast floor and anything darker fails it at data sizes.

### Semantic

| Status              | Name      | Hex       |
| ------------------- | --------- | --------- |
| Open / Ready        | Verdigris | `#4AAE8C` |
| Countdown / Playing | Brass     | `#C8A44E` |
| Running             | Ember     | `#DC6A51` |
| Finished            | Steel     | `#7BA2CC` |
| Draft / Muted       | Slate     | `#8791A0` |
| Danger (dark)       | Ember dk  | `#B5462F` |
| Streak freeze       | Frost     | `#9FD6E8` |

Frost exists so ice never borrows steel: "finished" owns the medium blue everywhere (signals, cards, week-line segments), while the freeze strip reads as a paler, colder cyan.

### Player lines

Each race participant gets a line color, assigned by join order (the server-side `color_index`), the way a metro line keeps its color across the whole network. It appears on: results rail left borders, map traces, finish board column lines and terminal marks, chat/popup identity dots, and the checked state of the map-filter checkboxes. It **never** colors the player's name (names belong to name templates).

The palette is the existing 20-hue `PLAYER_COLORS` in `web/src/lib/dag/constants.ts`, the single source of truth for every consumer. Twenty hues, not seven: dailies routinely exceed 20 participants, and bundled parallel map traces sit 5px apart, so mutual contrast is functional, not decorative. Saturated hues are kept on purpose (they read on navy, and real metro lines are saturated). The current values predate this charter (Tailwind-400 hexes); retune them lightly toward the navy/brass temperature when the new components start consuming them, keeping the tier structure and keeping tier 1 (the first six, the only ones most races ever show) clear of brass, ember and fog lookalikes. Cycle the palette past twenty participants.

---

## Typography

Three faces, three roles. All self-hosted (latin + latin-ext subsets in `web/static/fonts/`), no third-party font CDN.

| Role    | Face                                | Weights            | Used for                                                                    |
| ------- | ----------------------------------- | ------------------ | --------------------------------------------------------------------------- |
| Display | Barlow Condensed (`--font-display`) | 500 / 600 / 700    | Wordmark, page + section titles, race names, nav items, buttons, big labels |
| UI      | Public Sans (`--font-family`)       | 400-600 (variable) | Body text, descriptions, chat, form values                                  |
| Data    | Spline Sans Mono (`--font-mono`)    | 400-600 (variable) | IGT, deltas, seeds, dates, ranks, counts, signals, micro-labels             |

Loading: the `@font-face` declarations live in `web/static/fonts/fonts.css`,
linked statically from `app.html`, deliberately outside the Vite/SvelteKit CSS
pipeline (in dev, SvelteKit swaps its inline anti-FOUC copy of the route CSS
for Vite's injected copy at hydration; removing a stylesheet deregisters its
faces and every text on screen flashes). Faces are
declared with `font-display: fallback` (never `swap`; the app is
client-rendered, so faces load at consumption after first paint, and `swap`
turns that window into a visible system-font flash). The latin files
(Public Sans, Barlow Condensed 600/700, the mono) are preloaded in
`app.html`; latin-ext stays lazy. `/fonts/` is served long-cached by nginx.

### Scale

| Element                | Font    | Size             | Weight | Notes                                    |
| ---------------------- | ------- | ---------------- | ------ | ---------------------------------------- |
| Hero wordmark          | Display | clamp to context | 700    | Caps, `letter-spacing: 0.04em`           |
| H1 (page / race name)  | Display | `1.9rem`         | 700    | Caps, `letter-spacing: 0.03em`           |
| H2 (sections)          | Display | `1.25rem`        | 600    | Caps, brass, always with the line device |
| Card / cell titles     | Display | `1.15rem`        | 600    | Caps, ellipsize                          |
| Buttons                | Display | `1rem`           | 600    | Caps, `letter-spacing: 0.07em`           |
| Body                   | UI      | `0.9375rem`      | 400    |                                          |
| Data (IGT, seeds)      | Data    | `0.8rem`         | 400    | Tabular by design                        |
| Signals / micro-labels | Data    | `0.7rem`         | 500    | Caps, `letter-spacing: 0.09em`           |

### Principles

- **Caps diet.** Letterspaced uppercase survives only in two places: display-face titles/buttons, and mono micro-labels inside data panels (seed params, table headers, signals). Section titles never use the free-floating grey eyebrow pattern; they use the line device.
- **Usernames are never uppercased.** `text-transform` never applies to a player name: casing is part of the identity, and name templates style it deliberately. Display-face contexts (finish board, titles) render names in the display face with their original case. Race names and other non-name titles may be uppercased.
- Digits that align in columns always go through `--font-mono` (the face is tabular by design; `font-variant-numeric` is no longer needed for new code).
- Line-height: `1.5` body, `1.1`-`1.2` display.
- All transitions `0.2s ease`, never more.

---

## The Network Vocabulary

The DAG's own iconography, reused as the app's structural language. Draw these as CSS shapes or tiny inline SVGs, never emoji:

| Glyph                   | Meaning                                             |
| ----------------------- | --------------------------------------------------- |
| Filled triangle (brass) | Start                                               |
| Hollow ring             | Zone / station (terminal squares are always filled) |
| Diamond (fog)           | Boss                                                |
| Filled square           | Terminal / finished                                 |
| Moving dot on a line    | Race in progress                                    |
| Dashed line             | Not started / upcoming                              |
| `†` (dagger, ember)     | Deaths                                              |
| `DNF` (mono)            | Abandoned, in data rows                             |

**Section header device**: a small station ring + line segment in brass, followed by the display-caps title. This is the only decoration section titles get.

**Category markers** (dashboard activity, mixed lists): station ring = race, diamond = daily, square = solo, in the respective semantic hue.

---

## Components

### Buttons

Radius `--radius-md` (3px), display face, caps.

- **Primary**: brass background, near-black text (`#14100A`), hover `--color-gold-hover` + `--glow-gold`. Sparingly: one primary per view.
- **Secondary**: transparent, `1px` border `--color-border`, hover border + text fog.
- **Twitch**: unchanged (`#6441A5` / `#7C5BBF`).
- **Danger**: transparent, ember border/text, hover translucent ember fill.
- **Rage Quit**: the documented skeuomorphic exception (radial gradient, 3D press) survives as-is.

### Route-line cards

The standard clickable card (races, solo sessions). Radius `--radius-lg` (2px), surface background, `1px` border whose top side stays transparent: the 2px **route line** IS the card's top edge (markers sit just inside the corners and straddle it, punched with the surface color), so dashes never sit on a second stroke and full-height side elements like the Join strip reach the top. Hover recolors the remaining border sides in the route line's status hue. Both markers are always present, whatever the status: hollow start ring, filled terminal square, dim disabled grey until their state colors them. The line reads from the viewer's seat, with the same semantics as the daily week line:

- **Setup**: dashed disabled-grey line (dashes are reserved for races still in setup); hover stays grey, viewer registered or not. If the viewer is registered, their brass position dot waits in the start ring, the only brass on the card until the race starts. Joinability never colors the line: the verdigris `Join` strip and the `Open` signal carry it.
- **Running, viewer not aboard**: solid ember line and markers, small dot traveling along the line (CSS animation; respect `prefers-reduced-motion`).
- **Running, viewer riding** (registered through abandoned): the ridden stretch solid brass ending on the brass position dot, the boarding ring brass too, the stretch ahead staying grey; hover brass. Solo sessions always use this treatment whatever their status, the signal carrying the outcome. It replaces any separate progress bar.
- **Running, viewer finished**: solid verdigris.
- **Finished**: solid steel, whoever looks at it.

Status text is a **signal**, not a pill: a 7px square/ring in the status color + mono caps label, right-aligned on the title row. Signals reuse the existing status labels: `■ Finished` (steel), `● Live` (ember), `○ Open` (verdigris), and `○ Upcoming` (secondary grey ring) for a closed setup race. Further variants cover the rest of the platform's statuses: `● Active/Playing` (brass dot), `○ Ready` (verdigris ring), `○ Registered` (secondary ring), `■ DNF/Abandoned` (secondary square), `■ Cancelled` (disabled square). A joinable card keeps its verdigris `Join` strip on the right edge; the viewer's role renders as a **role mark** in the signals row, with non-circle glyphs so the row never strings identical rings: fog diamond `Organizing`, brass square `Participating`, twitch triangle `Casting`; label and glyph share the hue, except `Casting`, whose label stays secondary (both twitch purples fail the text contrast floor on surface). Card anatomy: title row (display caps + signals), crew row (avatar stack on the left, winner `1st Name` or `No finishers` centered, time ago on the right in mono), foot row (mono `N players · Mode` on the left, `by organizer` on the right).

The old vocabulary (8px radius, colored `border-left`, translucent pill chips) is fully retired: the `.badge-*` classes are gone from `app.css`, every status renders as a signal and every label-like fact as a chip. The route-line vocabulary (`.route`, `.route-setup/-running/-done/-finished`, the `.route-progress` variant carrying the viewer's brass run, `--route-hole` punch-through) lives in `app.css`; each state exposes its hue as `--route-color`, which the host card also uses for its hover border (the card root carries the state classes too). RaceCard and TrainingSessionCard are the only implementations; every surface listing races or sessions (home, `/races`, `/training`, the dashboard's Active Now) composes them. The timetable's continuous week line is its own scoped implementation in `DailyWeekGrid`. The traveling dot animates a transform only and disappears under `prefers-reduced-motion`.

### Daily timetable

The week grid is a timetable: one continuous bordered plate with 7 equal columns (`minmax(150px, 1fr)`, horizontal scroll below that) and hairline column separators. Riding the plate's top border runs **one continuous week line**: a start triangle before the first day and a filled terminal square after the last day, each taking its rim segment's color (the square is always filled, echoing the hero underline's terminal), with one hollow station centered on each day (straddling the border, punched with its cell's background). Each day colors its own segment: verdigris when the viewer finished that seed, steel for a closed day without them, and for today the seed's own state: ember with the traveling dot while it runs, brass line and dot while the viewer is riding it, verdigris with no dot once they are done; dashed border-grey for future or missing days; segments meet at hairline-thin breaks aligned with the column separators, reading as tick marks. Day + player count in mono micro-labels, mode name in display caps (a deathless day carries a mono ember `DEATHLESS` micro-label), winner line in mono (`1st Name · IGT`). The today cell sits on elevated surface (the old gold glow is retired); the toolbar keeps the streak/freeze info (mono, `❄` in text form, no flame) and the weekly winners under a mono brass `1st` tag.

**The today cell is the button**: the whole cell is one link, with a full-width strip pinned to its bottom edge. Strip hue taxonomy (kept from v1 behavior, hexes retuned):

| Strip                             | Style                                         |
| --------------------------------- | --------------------------------------------- |
| `Play now` / `Keep streak`        | Solid verdigris, near-black text (the action) |
| `In progress`                     | Translucent brass, brass text                 |
| `❄ Freeze`                        | Translucent frost, frost text                 |
| Finished result (`12/30 · 41:07`) | Translucent slate, verdigris mono text        |
| `DNF · IGT`                       | Translucent slate, secondary mono text        |
| `Abandoned`                       | Translucent slate, disabled text              |

Label strips use the display face in caps; result strips (finished, DNF) drop to mono and carry no check icon, the hue does the talking.

### Leaderboard rails (race / daily)

Vertical list, one entry per participant:

- 3px **left border** in the player's line color (top/bottom inset).
- Rank as plain mono `1.` in disabled grey; no circles, no medals.
- Name rendered through the equipped **name template** (`REWARDS.md`); background_css backdrops stay always-on here.
- Second row in mono: IGT, delta (`+13:36`), deaths (`† 16`) right-aligned; `DNF` for abandons, entry at `0.55` opacity.
- `● LIVE` ember signal; `✓` verdigris check for finished dailies.
- Click-to-filter mode: checkboxes appear per entry, checked state filled with the player's line color.

### Finish board (podium)

Three columns `1st / 2nd / 3rd` on a surface panel: place tag in mono brass caps, name in the display face through the **complete** name template, like a leaderboard row (original case, never uppercased; gradient on an inline link that shrink-wraps the text, equipped badge beside it, `background_css` backdrop on the whole column), IGT in mono (winner column larger), sub-line `+delta · † deaths`. Each column's top edge carries the player's line color. With fewer than three finishers, render only the existing columns (the board never shows empty slots).

### Forms

Element-level defaults in `app.css` (wrapped in `:where()` so any component's scoped styles keep winning) carry the input baseline and the native checkbox/radio `accent-color`; components only style what they need to differ.

- **Input**: `--color-bg` fill, `1px` border, radius `--radius-md`; focus: fog border + 1px fog ring.
- **Select**: input-shaped, `▾` chevron; menu on elevated surface, selected option in translucent fog.
- **Checkbox**: 15px square, radius 2px; checked: fog fill (or the player's line color in map-filter context), dark check.
- **Radio**: a station ring; checked: fog core dot.
- **Table**: mono caps micro-label headers, hairline row separators, numeric columns right-aligned in mono, hover row elevated.

### DAG / map

The SVG rendering (nodes, traces, animations, and its own color constants in `web/src/lib/dag/constants.ts`) is deliberately **out of the refresh's scope**: the current representation is kept as-is, and any cosmetic realignment is re-evaluated only once the rest of the refresh has shipped. It already speaks the network language: generous node sizes (they are click targets), rotated zone labels, boss diamonds, faint base network behind bundled player traces (parallel offsets, 45° elbows), abandoned traces ending on a hollow ring mid-network.

The HTML node popup does adopt the charter, but only through tokens (fonts, surface, border), keeping its structure: elevated surface, radius `--radius-lg`, zone title, mono meta row (`BOSS ARENA` / brass-bordered `TIER n` chip / `DEPTH n`; `FINAL BOSS` label in brass), caps `ENTRANCES` / `EXITS` sections with `←`/`→` arrows and mono `to:`/`from:` sub-notes, and a `VISITED BY` section listing per-player line-color dot + name + `† deaths · time` (DNF rows dimmed).

### Chat

System messages in mono `11px` muted with right-aligned timestamps. User messages: identity disc in the player's line color (slate for non-participants, e.g. spectators in public chat), name through the name template, mono timestamp, plain body. `ORG` tag as a small brass-bordered mono chip. Reactions as small bordered mono chips; the emoji itself is user content, not chrome, and is kept as-is next to its mono count.

---

## Logo

Wordmark only; the v1 network glyph is retired everywhere (header, favicon, OG images):

- **Wordmark**: `SPEEDFOG` in Barlow Condensed 700 caps, primary text color; `RACING` same size, weight 600, brass. The header lockup is the wordmark alone; the hero variant adds a brass route underline (triangle → ring → square).
- **Favicon**: the `SF` initials in Barlow Condensed 700 with the wordmark's double color (S primary, F brass) on a background-color plate, corner radius 112/512. Letterforms are outlined to paths: SVG favicons render without webfont access.
- **OG images**: the static share card centers the wordmark, the hero route underline and the tagline on the background color. The dynamic per-race and per-daily cards (server-rendered) carry the wordmark header, charter faces and greys, a status-colored route line on the top edge and a mono status signal; accents map setup → verdigris, running → ember, finished → steel, daily → brass.

`tools/generate_brand_assets.py` regenerates the static assets and the TTF conversions the server needs to rasterize the dynamic cards.

---

## Rewards (badges, name templates)

`REWARDS.md` owns the rewards visual spec. Charter-relevant contract:

- **Name templates remain the only zone** allowed gradients, translucent backdrops, `text-shadow` and alternative font families, on the name span only. The `name_css` allowlist's default stack is now the UI stack (Public Sans); the serif (Georgia) and mono system stacks are unchanged.
- Player line colors and name templates coexist: line color on structure, template on the name.
- The badge palette (`#9CA3AF` steel grey, `#A78BFA` purple, ambers) predates this charter; retune it to the new accent values when badges are next touched.

---

## CSS Custom Properties

Authoritative token block in `web/src/app.css` (self-hosted `@font-face` declarations in `web/static/fonts/fonts.css`):

```css
:root {
  /* Foundations */
  --color-bg: #0f1923;
  --color-surface: #162032;
  --color-surface-elevated: #1c2a3f;
  --color-border: #253550;

  /* Accents */
  --color-gold: #c8a44e;
  --color-gold-hover: #ddb95f;
  --color-purple: #a99bc9; /* "fog": interactive accent (hover, links) */
  --color-purple-hover: #c0b4dc;

  /* Text */
  --color-text: #e8e6e1;
  --color-text-secondary: #96a0ad;
  --color-text-disabled: #77808c;

  /* Semantic */
  --color-success: #4aae8c; /* verdigris */
  --color-warning: #c8a44e;
  --color-danger: #dc6a51; /* ember */
  --color-danger-dark: #b5462f;
  --color-info: #7ba2cc; /* steel */
  --color-frost: #9fd6e8; /* streak freeze: icy, paler than steel */

  /* Player line colors are NOT tokens: the 20-hue PLAYER_COLORS palette in
   * web/src/lib/dag/constants.ts is the single source of truth (see the
   * "Player lines" section). */

  /* Twitch */
  --color-twitch: #6441a5;
  --color-twitch-hover: #7c5bbf;

  /* Typography */
  --font-family:
    "Public Sans", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-display: "Barlow Condensed", "Arial Narrow", sans-serif;
  --font-mono:
    "Spline Sans Mono", ui-monospace, "SF Mono", Menlo, Consolas, monospace;
  --font-size-xs: 0.75rem;
  --font-size-sm: 0.8rem;
  --font-size-base: 0.9375rem;
  --font-size-lg: 1.25rem;
  --font-size-xl: 1.5rem;
  --font-size-2xl: 1.75rem;

  /* Spacing */
  --radius-sm: 2px;
  --radius-md: 3px;
  --radius-lg: 2px;

  /* Effects */
  --transition: 0.2s ease;
  --glow-gold: 0 0 12px rgba(200, 164, 78, 0.25);
}
```
