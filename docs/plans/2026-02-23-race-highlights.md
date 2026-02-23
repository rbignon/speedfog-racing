# Race Highlights & Replay Timeline

**Date:** 2026-02-23
**Status:** Approved

## Overview

Display fun, interesting highlights on the race detail page for finished races — notable stats and memorable moments computed from zone_history data. Future phase adds a timeline replay to "relive" the race.

## Data Available

Each participant has `zone_history`: ordered list of zone entries:

```json
[
  { "node_id": "chapel_start_4f96", "igt_ms": 0 },
  { "node_id": "volcano_ac44", "igt_ms": 12500 },
  { "node_id": "limgrave_cave_da80", "igt_ms": 45000, "deaths": 2 }
]
```

Combined with `graph_json` (nodes with tier/layer/type, edges), this enables per-zone time computation, death attribution, path comparison, and layer-based progression analysis.

## Phase 1: Static Highlights (FINISHED races)

### Placement

New section after `<RaceStats>` in the race detail page, only shown when:

- `status === FINISHED`
- At least 2 participants have zone_history data

### Component

`<RaceHighlights>` receives `participants` (WsParticipant[]) and `graphJson`.

### Format

List of 5-6 items, each with:

- Short catchy title (e.g., "Speed Demon")
- Description with player name and context
- Player name colored with their participant color

### Computation

Pure TypeScript function `computeHighlights(participants, graphJson) → Highlight[]`:

1. Compute all candidate highlights (14 types below)
2. Score each candidate by amplitude + rarity + zone tier
3. Apply diversity filter (max 2 highlights from same category)
4. Return top 5-6

### Highlight Catalogue

#### Time / Speed

| #   | Name         | Computation                                                | Score boost |
| --- | ------------ | ---------------------------------------------------------- | ----------- |
| 1   | Speed Demon  | min(player_time / avg_time) per zone visited by 2+ players | High tier   |
| 2   | Zone Wall    | max(player_time / avg_time) per zone                       | High tier   |
| 3   | Fast Starter | Player reaching layer 2 fastest                            | Gap vs 2nd  |
| 4   | Sprint Final | Player completing last tier fastest                        | Gap vs avg  |

#### Deaths

| #   | Name         | Computation                                            | Score boost    |
| --- | ------------ | ------------------------------------------------------ | -------------- |
| 5   | Graveyard    | Zone with most cumulative deaths (all players)         | Absolute count |
| 6   | Death Zone   | max(single player deaths in one zone)                  | High tier      |
| 7   | Deathless    | Player crossing tier 3+ zone with 0 deaths             | Zone tier      |
| 8   | Comeback Kid | Player with most deaths who still finished well-placed | Placement gap  |

#### Path / Exploration

| #   | Name               | Computation                                 | Score boost          |
| --- | ------------------ | ------------------------------------------- | -------------------- |
| 9   | Road Less Traveled | min(shared nodes with others) / total nodes | More unique = better |
| 10  | Same Brain         | Two players with identical path             | Node count           |
| 11  | Détour             | Player with most nodes visited              | Gap vs avg           |

#### Competitive / Comparison

| #   | Name         | Computation                                | Score boost          |
| --- | ------------ | ------------------------------------------ | -------------------- |
| 12  | Photo Finish | min(IGT gap between consecutive finishers) | Smaller gap = better |
| 13  | Lead Change  | Number of leader changes across layers     | More = better        |
| 14  | Dominant     | Player leading at every layer              | Layer count          |

### Edge Cases

- 1 participant: no highlights section shown (comparisons meaningless)
- Abandoned players: included in calculations if they have zone_history
- Zones visited by only 1 player: excluded from Speed Demon / Zone Wall

### Architecture

- **Approach A (frontend-only):** All computation in TypeScript, no backend changes
- zone_history and graph_json already available via WebSocket/API
- Data is small (dozens of entries per participant), computation trivial
- Can cache/memoize with `$derived` in SvelteKit

### Files

- `web/src/lib/highlights.ts` — `computeHighlights()` pure function + types
- `web/src/lib/components/RaceHighlights.svelte` — display component
- `web/src/routes/race/[id]/+page.svelte` — integrate after RaceStats

## Phase 2: Timeline Replay (future, separate design)

### Concept

A time scrubber over the race's total IGT. Moving it shows players progressing on the DAG. Phase 1 highlights are annotated as markers on the timeline.

### Component

`<RaceReplay>` — reuses MetroDagFull with state filtered by timestamp.

### Scope

To be designed in detail separately. Phase 1 highlight computation provides the foundation for timeline annotations.
