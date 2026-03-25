# Personal Highlights

Player-specific highlights shown in a dedicated tab on the finished race page, visible only to participants.

## Context

The finished race page currently shows up to 6 global highlights (from 17 detectors across 4 categories). These are race-level moments visible to everyone. This feature adds a "Your Race" tab with highlights centered on the viewing player's experience, using a direct tone ("You...", "Your...") and always comparing against other participants.

## Architecture

### New file: `web/src/lib/personal-highlights.ts`

- Exports `computePersonalHighlights(myParticipantId: string, participants: WsParticipant[], graphJson: Record<string, unknown>): Highlight[]`
- Reuses types from `highlights.ts`: `DescriptionSegment`, `ZoneTime`
- The `Highlight` interface in `highlights.ts` has `category: HighlightCategory` where `HighlightCategory = "speed" | "deaths" | "path" | "competitive"`. To support personal categories, widen the type: `HighlightCategory = "speed" | "deaths" | "path" | "competitive" | "combat" | "pathing"`. This keeps type safety (no `string`) while allowing both global and personal detectors to produce `Highlight` objects. The global selection logic only encounters global categories, and the personal selection logic only encounters personal ones.
- Reuses helpers from `highlights.ts` (newly exported): `buildNodeInfo`, `pSeg`, `zSeg`, `tSeg`, `formatTime`, `uniqueNodePath`, `buildZonePlayerTimes`
- Note: `computeZoneTimes` is already exported
- The orchestrator pre-builds `allZoneTimes: Map<string, ZoneTime[]>` (one entry per participant) and passes it to detectors, same pattern as the global orchestrator
- Adds a new internal helper `computeRanksPerLayer(participants, nodeInfo): Map<number, Map<string, number>>` that returns each player's rank (1-based) at each layer, based on earliest IGT to reach that layer. Used by `comeback`, `lead_swap`, and `neck_and_neck`. `computeLeadersPerLayer` (from `highlights.ts`) is not sufficient as it only returns the leader, not full rankings.
- 15 internal detector functions, each returning `Highlight | null`

### Modified: `web/src/lib/components/RaceHighlights.svelte`

- New optional prop: `myParticipantId?: string`
- When provided: renders "Race" / "Your Race" toggle tabs (same style as `dag-view-toggle`)
- When absent: no tabs, unchanged behavior
- "Your Race" tab calls `computePersonalHighlights()` and renders results with the same highlight item layout
- If no personal highlights found: shows "No personal highlights for this race."

### Modified: `web/src/routes/race/[id]/+page.svelte`

- Passes `myParticipantId={myWsParticipant?.id}` to `RaceHighlights`
- No other changes needed

### Helpers to export from `highlights.ts`

The following currently-internal helpers need to be exported:

- `buildNodeInfo` (and `NodeInfo` type)
- `pSeg`, `zSeg`, `tSeg`
- `formatTime`, `shortName`
- `uniqueNodePath`
- `buildZonePlayerTimes`

## Detectors

### Category: combat (5 detectors)

**boss_slayer** - "You only died X times on **Boss** (average: Y)"

- Condition: player's deaths on a boss significantly below field average (ratio < 0.5)
- Score: `(1 - ratio) * 100 * tierMult`
- Boss nodes identified by `type === "boss"` or `type === "final_boss"` in graph_json

**boss_wall** - "**Boss** gave you trouble: X deaths (average: Y)"

- Condition: player's deaths on a boss significantly above field average (ratio > 2x)
- Score: `ratio * 30`
- Min 2 players on the boss

**stood_your_ground** - "You're the only one who didn't turn back from **Zone**"

- Condition: other players visited the zone but backtracked (outcome "backed"); this player cleared it
- Score: `backedCount * 35 * tierMult`

**death_spiral** - "You left X lives on **Zone** before finally pushing through"

- Condition: zone with 5+ deaths but outcome "cleared"
- Score: `deaths * 15 * tierMult`

**clean_streak** - "You cleared X zones in a row without dying, while others lost Y lives there"

- Condition: 3+ consecutive zones with 0 deaths, where other players collectively had deaths
- Score: `streakLen * 25 + othersDeaths * 5`

### Category: pathing (4 detectors)

**lone_explorer** - "You're the only one who visited **Zone**"

- Condition: no other participant has the zone in their zone_history
- Score: `participantCount * 20`

**against_the_flow** - "At the **Zone** crossroads, you took a path no one else did"

- Condition: at a fork in the DAG (node with 2+ outgoing edges), the player chose a branch that no other player took
- Branch detection: for each fork node in the player's zone_history, look at the first child node visited after the fork (using `uniqueNodePath` to ignore backtracks). Compare against other players' first child after the same fork. If the player's branch is unique, the highlight triggers.
- Score: `otherPlayersCount * 30`
- Uses graph_json edges to identify forks

**smart_backtrack** - "Good call turning back from **Zone**: those who stayed spent X:XX longer on average"

- Condition: player backtracked from a zone (outcome "backed"), and players who cleared it spent significantly more time
- Score: `timeSavedMs / 1000 * 2`
- Min 1 other player who cleared the zone for comparison

**costly_detour** - "Your detour through **Zone** cost you X:XX compared to those who skipped it"

- Condition: player visited a zone that better-ranked finishers did not visit, with measurable time cost
- `timeLostMs` = total time the player spent in that zone (from `computeZoneTimes`)
- Score: `timeLostMs / 1000 * 1.5`

### Category: competitive (6 detectors)

**faster_than_all** - "You were the fastest through **Zone**: X:XX (average: Y:XX)"

- Condition: best time among all participants on a cleared zone (ratio < 0.6x average, min 2 players)
- Score: `(1 - ratio) * 100 * tierMult`

**slower_than_all** - "**Zone** slowed you down: last with X:XX (average: Y:XX)"

- Condition: worst time among all participants on a zone (ratio > 1.5x average, min 2 players)
- Score: `(ratio - 1) * 50`

**lead_lost** - "You were leading the race, but lost the lead at layer X"

- Condition: player was rank 1 at some layer but not at the next
- Score: `60` (fixed, strong narrative moment)
- Uses `computeRanksPerLayer()`

**comeback** - "You were Xth at layer Y before climbing back to Zth place"

- Condition: player's rank improved by 2+ positions between two layers
- Score: `positionsGained * 30`
- Uses `computeRanksPerLayer()`

**lead_swap** - "You and **Player** traded the lead X times during the race"

- Condition: player and another player alternated as rank 1 across 3+ layers
- Score: `swapCount * 25`
- Uses `computeRanksPerLayer()`

**neck_and_neck** - "You stayed neck and neck with **Player** throughout the race"

- Condition: two players within 1 rank of each other for 70%+ of layers, and final IGT gap < 10%
- Score: `layersTogether * 10`
- Uses `computeRanksPerLayer()`

## Selection Algorithm

1. Run all 15 detectors, collect non-null candidates
2. Sort by score descending
3. Filter:
   - Max 2 per category (combat / pathing / competitive)
   - No zone reuse between selected highlights
4. Cap at 6 highlights
5. No community boost (all highlights are personal)

## Tone and Language

- English throughout (consistent with global highlights)
- Direct address: "You", "Your" (never names the current player)
- Other players named normally via `pSeg()` with their color
- Zones clickable via `zSeg()` (triggers DAG focus, same as global highlights)

## Edge Cases

- **Minimum participants**: 2+ participants with zone_history required (same as globals)
- **Abandoned players**: see their personal highlights; detectors handle abandoned status naturally
- **No highlights found**: "Your Race" tab shows "No personal highlights for this race." (tab remains visible)
- **Small races (2 players)**: detectors work but produce lower scores (by design, less remarkable)
- **Non-participant visitors**: no `myParticipantId` prop, no tabs shown, global highlights only
