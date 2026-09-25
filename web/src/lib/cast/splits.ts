import type { ZoneHistoryEntry } from "$lib/zone-history";

/** One zone the runner has finished crossing, and how long they spent there. */
export interface CastSplit {
  zone: string;
  durationMs: number;
}

const MAX_SPLITS = 3;
const ZONE_LABEL_MAX = 20;

// A resolved node name is a whole route label ("Gravesite Plain - Belurat
// Gaol - Demi-Human Swordmaster Onze"), not a short zone name: strip the
// region prefix and cap the length, exactly like `RunnerCard.zoneLabel` does
// for the current-zone line on the very same card (also duplicated in
// Leaderboard.svelte and across web/src/lib/dag/, this codebase's established
// way of shortening a node name rather than a shared helper). The split list
// and the current-zone line must agree on what a zone is called, or the
// panel shows the same runner's location named two different ways at once.
function zoneLabel(name: string): string {
  const short = name.includes(" - ") ? name.split(" - ").pop()! : name;
  return short.length > ZONE_LABEL_MAX
    ? short.slice(0, ZONE_LABEL_MAX - 1) + "…"
    : short;
}

/**
 * The runner's last few completed zone splits, most recent first.
 *
 * `zone_history` entries carry `node_id` and `igt_ms`, the IGT at which the
 * runner entered that zone (see `ZoneHistoryEntry`), with no explicit exit
 * time. A split only exists once the *next* entry confirms when the runner
 * left, so consecutive entries are paired to derive a duration; the zone the
 * runner currently stands in never becomes a split, since it isn't finished
 * yet (`RunnerCard` already shows it as the current zone, not a split).
 *
 * `nodeNames` is the same node id -> display name map the quad page builds
 * from the seed's graph (`parseDagGraph(...).nodes`); a miss (the graph
 * hasn't resolved that id yet) resolves to an empty zone name, matching
 * `RunnerCard.zoneLabel`'s own miss case rather than printing a raw node id.
 */
export function buildCastSplits(
  history: ZoneHistoryEntry[] | null,
  nodeNames: Map<string, string>,
): CastSplit[] {
  if (!history || history.length < 2) return [];
  const completed: CastSplit[] = [];
  for (let i = 0; i < history.length - 1; i++) {
    const name = nodeNames.get(history[i].node_id);
    completed.push({
      zone: name ? zoneLabel(name) : "",
      durationMs: history[i + 1].igt_ms - history[i].igt_ms,
    });
  }
  return completed.slice(-MAX_SPLITS).reverse();
}
