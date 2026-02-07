# SpeedFog Racing — Graphic Charter

## Design Direction

**Hybrid**: clean esport/dashboard base with subtle Elden Ring touches through color only. Sobriety first — the dark theme does the heavy lifting, gold appears sparingly as punctuation on high-value elements.

**Effects philosophy**: flat design with subtle depth. Light glow on active elements, fine borders, soft shadows. No gradients, no blur, no background textures.

---

## Color Palette

### Foundations (~90% of surface area)

| Role             | Color                     | Hex       |
| ---------------- | ------------------------- | --------- |
| Background       | Deep blue-black           | `#0F1923` |
| Surface          | Very dark blue-grey       | `#162032` |
| Surface elevated | Blue-grey (hover, modals) | `#1C2A3F` |
| Border           | Subtle blue-grey          | `#253550` |

### Accents

| Role                  | Color         | Hex       |
| --------------------- | ------------- | --------- |
| Gold — primary accent | Warm amber    | `#C8A44E` |
| Gold — hover/glow     | Light amber   | `#DDB95F` |
| Purple — secondary    | Medium purple | `#8B5CF6` |
| Purple — hover        | Light purple  | `#A78BFA` |

**Gold usage (exhaustive list):** logo, section h2 headings, primary CTA button, "running" race card left border, leaderboard #1 rank number. Nowhere else.

**Purple usage:** interactive element hover states (card borders, secondary buttons), connected player highlight, links, secondary accents.

### Text

| Role      | Color      | Hex       |
| --------- | ---------- | --------- |
| Primary   | Off-white  | `#E8E6E1` |
| Secondary | Light grey | `#9CA3AF` |
| Disabled  | Grey       | `#6B7280` |

### Semantic (status badges)

| Status              | Color         | Hex       |
| ------------------- | ------------- | --------- |
| Open / Ready        | Emerald green | `#10B981` |
| Countdown / Playing | Amber (gold)  | `#C8A44E` |
| Running             | Bright red    | `#EF4444` |
| Finished            | Steel blue    | `#3B82F6` |
| Draft / Registered  | Grey          | `#6B7280` |
| Abandoned / Error   | Dark red      | `#DC2626` |

---

## Typography

**Single font: Inter** (Google Fonts). Hierarchy through weight and color, not font variety.

### Scale

| Element                    | Size        | Weight | Color     | Notes                                 |
| -------------------------- | ----------- | ------ | --------- | ------------------------------------- |
| Logo "SpeedFog Racing"     | `1.5rem`    | 700    | `#C8A44E` | Only permanent gold element           |
| H1 (race name)             | `1.75rem`   | 600    | `#E8E6E1` | Not gold — sobriety                   |
| H2 (sections)              | `1.25rem`   | 600    | `#C8A44E` | "My Races", "Active Races", etc.      |
| Body                       | `0.9375rem` | 400    | `#E8E6E1` |                                       |
| Small / labels             | `0.8rem`    | 500    | `#9CA3AF` | `uppercase`, `letter-spacing: 0.05em` |
| Numeric data (IGT, layers) | `0.9375rem` | 600    | `#E8E6E1` | `font-variant-numeric: tabular-nums`  |
| Badges                     | `0.75rem`   | 600    | white     | `uppercase`                           |

### Principles

- `tabular-nums` on all numeric data for column alignment
- `letter-spacing: 0.05em` on uppercase labels
- Line-height: `1.5` body, `1.2` headings
- All transitions: `0.2s ease`, never more

---

## Components

### Buttons

**Primary (CTA)** — used sparingly: "Create Race", "Manage Race"

- Background: `#C8A44E`
- Text: `#0F1923` (strong contrast)
- Hover: `#DDB95F` + `box-shadow: 0 0 12px rgba(200, 164, 78, 0.25)`
- Border-radius: `6px`

**Secondary** — common actions: "Download", "Logout"

- Background: `transparent`
- Border: `1px solid #253550`
- Text: `#E8E6E1`
- Hover: border `#8B5CF6`, text `#A78BFA`

**Twitch** — "Login with Twitch"

- Background: `#6441A5`
- Hover: `#7C5BBF`

**Danger** — "Delete Race", "Kick"

- Background: `transparent`
- Border: `1px solid #DC2626`
- Text: `#EF4444`
- Hover: background `rgba(220, 38, 38, 0.1)`

### Cards (race cards)

- Background: `#162032`
- Border: `1px solid #253550`
- Border-radius: `8px`
- Padding: `1.25rem`
- Hover: border becomes `#8B5CF6` (purple, not gold)
- Transition: `border-color 0.2s ease`
- **Exception**: a "running" race card gets `border-left: 3px solid #C8A44E` — only gold hint, discreet

### Badges

- Border-radius: `4px`
- Padding: `0.2rem 0.6rem`
- Font: `0.75rem`, weight 600, uppercase
- Translucent style: `background: rgba(color, 0.15)` + `color: color`
- Lighter and more integrated than opaque fills on dark backgrounds
- **Contrast floor**: for low-luminance colors (grey `#6B7280`, red `#DC2626`), bump opacity to `0.20` or use a lighter foreground to maintain readability

### Leaderboard

- Header "Leaderboard": `#C8A44E` (h2)
- Position #1: rank number in gold `#C8A44E`
- Positions #2+: rank number in `#9CA3AF` grey
- Row separator: `border-bottom: 1px solid #253550`
- Row hover: `background: #1C2A3F`
- IGT data: `tabular-nums`, right-aligned
- Connected player: `background: rgba(139, 92, 246, 0.08)` (very subtle purple)

### Header / Navbar

- Background: `#0F1923` (same as body — no hard separation)
- Bottom separator: `border-bottom: 1px solid #253550`
- Logo: only gold element, weight 700
- Twitch avatar: `border-radius: 50%`, `border: 2px solid #253550`

### Subtle effects

- Gold glow on primary CTA hover only: `box-shadow: 0 0 12px rgba(200, 164, 78, 0.25)`
- Purple borders on interactive element hover (cards, secondary buttons)
- All transitions: `0.2s ease`
- No gradients, no blur, no textured backgrounds

---

## CSS Custom Properties

Reference tokens for implementation. Import Inter via Google Fonts (`wght@400;500;600;700`).

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
  --color-purple: #8b5cf6;
  --color-purple-hover: #a78bfa;

  /* Text */
  --color-text: #e8e6e1;
  --color-text-secondary: #9ca3af;
  --color-text-disabled: #6b7280;

  /* Semantic */
  --color-success: #10b981;
  --color-warning: #c8a44e;
  --color-danger: #ef4444;
  --color-danger-dark: #dc2626;
  --color-info: #3b82f6;

  /* Typography */
  --font-family:
    "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
  --font-size-xs: 0.75rem;
  --font-size-sm: 0.8rem;
  --font-size-base: 0.9375rem;
  --font-size-lg: 1.25rem;
  --font-size-xl: 1.5rem;
  --font-size-2xl: 1.75rem;

  /* Spacing */
  --radius-sm: 4px;
  --radius-md: 6px;
  --radius-lg: 8px;

  /* Effects */
  --transition: 0.2s ease;
  --glow-gold: 0 0 12px rgba(200, 164, 78, 0.25);
}
```
