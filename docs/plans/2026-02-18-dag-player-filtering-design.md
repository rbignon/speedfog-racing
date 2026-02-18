# DAG Player Filtering

Click a player in the Leaderboard sidebar to highlight only their path on MetroDagResults. Ctrl+click for multi-select. Three reset methods: click sole-selected player again, "Show all" button, or Escape key.

## Components Touched

1. **`+page.svelte`** — new `selectedParticipantIds: Set<string>` state, selection logic, prop passing
2. **`Leaderboard.svelte`** — new `selectedIds` prop, `onToggle(id, ctrlKey)` event, visual feedback, "Show all" button, Escape listener
3. **`MetroDagResults.svelte`** — new `highlightIds` prop, opacity dimming on non-selected paths/dots

## Data Flow

```
+page.svelte
  ├── selectedParticipantIds: Set<string>
  ├── Leaderboard
  │     props: selectedIds={selectedParticipantIds}
  │     event: onToggle(participantId, ctrlKey) → page handler
  └── MetroDagResults
        props: highlightIds={selectedParticipantIds}
        (empty Set = all visible at full opacity)
```

## Interaction Logic

```
handleLeaderboardToggle(id, ctrlKey):
  if ctrlKey:
    toggle id in/out of Set
  else:
    if Set has exactly 1 entry and it's this id:
      clear Set (deselect = reset)
    else:
      Set = {id} (solo select)
```

## Leaderboard Changes

- Each `<li>` becomes clickable (cursor: pointer, onclick)
- When `selectedIds` is non-empty: selected entries get `var(--color-surface-elevated)` background
- Non-selected entries stay normal (no dim — leaderboard must remain navigable)
- Header: "Show all" link visible only when `selectedIds.size > 0`
- `svelte:window` listens for Escape keydown → reset

## MetroDagResults Changes

- New optional prop: `highlightIds?: Set<string>`
- Empty/undefined → current behavior (all at opacity 0.8)
- Non-empty:
  - Polylines in set → opacity 0.8
  - Polylines not in set → opacity 0.1
  - Final dots: same (0.8 vs 0.1)
  - CSS transition `opacity 200ms`
- Base edges and nodes unchanged

## Reset UX

1. Click sole-selected player again → toggle off → empty Set
2. "Show all" button in Leaderboard header
3. Escape key → clear Set

## Not In Scope

- No filtering of base graph nodes/edges
- No dim on Leaderboard entries
- No shared store — local page state only
- Does not apply to MetroDagProgressive
- No persistence across navigation
