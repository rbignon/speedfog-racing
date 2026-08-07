# SpeedFog Racing - Graphic Charter

## Design Direction

**"Timetable of the Lands Between"**: the fog-gate network is the identity. The metro-map DAG is not an illustration on top of the product, it _is_ the product, so its vocabulary (lines, stations, terminals) carries structure and status everywhere, and the typography speaks public-transit signage and race timing boards.

The sobriety discipline of the previous charter survives intact: the dark theme does the heavy lifting, gold appears sparingly as punctuation on high-value elements, flat design with subtle depth (fine borders, soft glows on active elements only). No gradients, no blur, no background textures, outside the two documented exception zones (Rage Quit button, name templates).

What changed versus charter v1, in one list:

- Inter is replaced by the **Barlow superfamily** (Condensed for display, regular for UI) plus **Spline Sans Mono** for data. Three roles, one voice.
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

### Accents

| Role               | Color            | Hex       |
| ------------------ | ---------------- | --------- |
| Brass (primary)    | Warm amber gold  | `#C8A44E` |
| Brass (hover/glow) | Light amber      | `#DDB95F` |
| Fog (secondary)    | Misty heliotrope | `#A99BC9` |
| Fog (hover)        | Light heliotrope | `#C0B4DC` |

**Brass usage (exhaustive list):** logo glyph and the "Racing" half of the wordmark, section header device + title, primary CTA button, start/terminal markers and today's route line accents, 1st-place markers (`1st` labels, finish board place tags), the amber "running" daily strip. Nowhere else.

**Fog usage:** interactive hover states (card borders, secondary buttons), links, focus rings, boss diamonds on the DAG, radio/checkbox checked states (outside player-colored contexts).

### Text

| Role      | Color            | Hex       |
| --------- | ---------------- | --------- |
| Primary   | Off-white        | `#E8E6E1` |
| Secondary | Blue-tinted grey | `#96A0AD` |
| Disabled  | Slate grey       | `#77808C` |

### Semantic

| Status              | Name      | Hex       |
| ------------------- | --------- | --------- |
| Open / Ready        | Verdigris | `#4AAE8C` |
| Countdown / Playing | Brass     | `#C8A44E` |
| Running             | Ember     | `#DC6A51` |
| Finished            | Steel     | `#7BA2CC` |
| Draft / Muted       | Slate     | `#8791A0` |
| Danger (dark)       | Ember dk  | `#B5462F` |

### Player lines

Each race participant gets a line color, assigned by join order, the way a metro line keeps its color across the whole network. It appears on: results rail left borders, map traces, finish board column lines and terminal marks, chat/popup identity dots, and the checked state of the map-filter checkboxes. It **never** colors the player's name (names belong to name templates).

| Index | Hex       |
| ----- | --------- |
| 1     | `#4AAE8C` |
| 2     | `#C8A44E` |
| 3     | `#A99BC9` |
| 4     | `#D96A6A` |
| 5     | `#7BA2CC` |
| 6     | `#C98F65` |
| 7     | `#8791A0` |

Brass and verdigris double as line colors on purpose; on a metro map, hue reuse is normal. Cycle the palette past seven participants.

---

## Typography

Three faces, three roles. All self-hosted (latin + latin-ext subsets in `web/static/fonts/`), no third-party font CDN.

| Role    | Face                                | Weights            | Used for                                                                    |
| ------- | ----------------------------------- | ------------------ | --------------------------------------------------------------------------- |
| Display | Barlow Condensed (`--font-display`) | 500 / 600 / 700    | Wordmark, page + section titles, race names, nav items, buttons, big labels |
| UI      | Barlow (`--font-family`)            | 400 / 500 / 600    | Body text, descriptions, chat, form values                                  |
| Data    | Spline Sans Mono (`--font-mono`)    | 400-600 (variable) | IGT, deltas, seeds, dates, ranks, counts, signals, micro-labels             |

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
- Digits that align in columns always go through `--font-mono` (the face is tabular by design; `font-variant-numeric` is no longer needed for new code).
- Line-height: `1.5` body, `1.1`-`1.2` display.
- All transitions `0.2s ease`, never more.

---

## The Network Vocabulary

The DAG's own iconography, reused as the app's structural language. Draw these as CSS shapes or tiny inline SVGs, never emoji:

| Glyph                   | Meaning                                        |
| ----------------------- | ---------------------------------------------- |
| Filled triangle (brass) | Start                                          |
| Hollow ring             | Zone / station; also "not ridden yet" terminal |
| Diamond (fog)           | Boss                                           |
| Filled square           | Terminal / finished                            |
| Moving dot on a line    | Race in progress                               |
| Dashed line             | Not started / upcoming                         |
| `†` (dagger, ember)     | Deaths                                         |
| `DNF` (mono)            | Abandoned, in data rows                        |

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

The standard clickable card (races, dailies). Radius `--radius-lg` (2px), surface background, `1px` border, hover border fog. The top edge carries a 2px **route line** whose style encodes status:

- **Open**: dashed verdigris line, hollow ring at both ends (the route is not ridden yet).
- **Running**: solid ember line, small dot traveling along it (CSS animation; respect `prefers-reduced-motion`), hollow terminal.
- **Finished**: solid steel line, filled square terminal at the right end.

Status text is a **signal**, not a pill: a 7px square/ring in the status color + mono caps label (`■ FINISHED`, `● RUNNING`, `○ OPEN`), right-aligned on the title row. Card anatomy: title row (display caps + signal), meta row (mono: `N players · Mode · extras`), foot row (avatar disc stack + winner `1st Name` or `No finishers` on the left; `by organizer · time ago` in mono on the right).

The old vocabulary (8px radius, colored `border-left`, translucent pill chips) is retired; `.badge-*` classes in `app.css` remain only until every consumer migrates to signals.

### Daily timetable

The week grid is a timetable: 7 equal columns (`min-width: 0`), hairline separators, each cell topped by a small route line (steel solid + square for closed days with a winner, ember + dot for today, dashed border-grey for future days). Day + player count in mono micro-labels, mode name in display caps, winner line in mono (`1st Name · IGT`).

**The today cell is the button**: the whole cell is one link, with a full-width strip pinned to its bottom edge. Strip hue taxonomy (kept from v1 behavior, hexes retuned):

| Strip                             | Style                                         |
| --------------------------------- | --------------------------------------------- |
| `Play now` / `Keep streak`        | Solid verdigris, near-black text (the action) |
| `In progress`                     | Translucent brass, brass text                 |
| `❄ Freeze`                        | Translucent steel, steel text                 |
| Finished result (`12/30 · 41:07`) | Translucent slate, verdigris text, justified  |
| `DNF · IGT`                       | Translucent slate, muted text                 |
| `Abandoned`                       | Translucent slate, disabled text              |

### Leaderboard rails (race / daily)

Vertical list, one entry per participant:

- 3px **left border** in the player's line color (top/bottom inset).
- Rank as plain mono `1.` in disabled grey; no circles, no medals.
- Name rendered through the equipped **name template** (`REWARDS.md`); background_css backdrops stay always-on here.
- Second row in mono: IGT, delta (`+13:36`), deaths (`† 16`) right-aligned; `DNF` for abandons, entry at `0.55` opacity.
- `● LIVE` ember signal; `✓` verdigris check for finished dailies.
- Click-to-filter mode: checkboxes appear per entry, checked state filled with the player's line color.

### Finish board (podium)

Three columns `1st / 2nd / 3rd` on a surface panel: place tag in mono brass caps, name in display caps through the name template, IGT in mono (winner column larger), sub-line `+delta · † deaths`. Each column's top edge carries the player's line color with a small terminal square. With fewer than three finishers, render only the existing columns (the board never shows empty slots).

### Forms

- **Input**: `--color-bg` fill, `1px` border, radius `--radius-md`; focus: fog border + 1px fog ring.
- **Select**: input-shaped, `▾` chevron; menu on elevated surface, selected option in translucent fog.
- **Checkbox**: 15px square, radius 2px; checked: fog fill (or the player's line color in map-filter context), dark check.
- **Radio**: a station ring; checked: fog core dot.
- **Table**: mono caps micro-label headers, hairline row separators, numeric columns right-aligned in mono, hover row elevated.

### DAG / map

The map keeps its full richness: generous node sizes (they are click targets), rotated zone labels, fog boss diamonds, dagger death marks, faint base network behind bundled player traces (parallel offsets, 45° elbows). Abandoned traces end on a hollow ring mid-network. Node popup on elevated surface, radius `--radius-lg`: zone title, mono meta row (`BOSS ARENA` / brass-bordered `TIER n` chip / `DEPTH n`; `FINAL BOSS` label in brass), caps `ENTRANCES` / `EXITS` sections with `←`/`→` arrows and mono `to:`/`from:` sub-notes, and a `VISITED BY` section listing per-player line-color dot + name + `† deaths · time` (DNF rows dimmed).

### Chat

System messages in mono `11px` muted with right-aligned timestamps. User messages: identity disc in the player's line color, name through the name template, mono timestamp, plain body. `ORG` tag as a small brass-bordered mono chip. Reactions as small bordered mono chips.

---

## Logo

Network glyph + wordmark:

- **Glyph**: start triangle forking into two branches (station ring on one, fog boss diamond on the other) merging into a terminal square. Brass strokes, one fog accent. Doubles as favicon and loading mark. The current geometry is a v1; iterate before final asset production.
- **Wordmark**: `SPEEDFOG` in Barlow Condensed 700 caps, primary text color; `RACING` same size, weight 600, brass. Header lockup = glyph + wordmark; hero variant adds a brass route underline (triangle → ring → square).

The logo replaces the former gold-Inter text logo everywhere (header, OG images, favicon).

---

## Rewards (badges, name templates)

`REWARDS.md` owns the rewards visual spec. Charter-relevant contract:

- **Name templates remain the only zone** allowed gradients, translucent backdrops, `text-shadow` and alternative font families, on the name span only. The `name_css` allowlist's default stack is now the Barlow stack; the serif (Georgia) and mono system stacks are unchanged.
- Player line colors and name templates coexist: line color on structure, template on the name.
- The badge palette (`#9CA3AF` steel grey, `#A78BFA` purple, ambers) predates this charter; retune it to the new accent values when badges are next touched.

---

## CSS Custom Properties

Authoritative token block in `web/src/app.css` (self-hosted `@font-face` declarations above it):

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

  /* Player lines */
  --color-line-1: #4aae8c;
  --color-line-2: #c8a44e;
  --color-line-3: #a99bc9;
  --color-line-4: #d96a6a;
  --color-line-5: #7ba2cc;
  --color-line-6: #c98f65;
  --color-line-7: #8791a0;

  /* Twitch */
  --color-twitch: #6441a5;
  --color-twitch-hover: #7c5bbf;

  /* Typography */
  --font-family:
    "Barlow", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
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
