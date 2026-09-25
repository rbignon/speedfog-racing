import type { ZoneHistoryEntry } from "$lib/zone-history";

/** One zone the runner has finished crossing, and how long they spent there. */
export interface CastSplit {
  zone: string;
  durationMs: number;
}

const MAX_SPLITS = 3;

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
    completed.push({
      zone: nodeNames.get(history[i].node_id) ?? "",
      durationMs: history[i + 1].igt_ms - history[i].igt_ms,
    });
  }
  return completed.slice(-MAX_SPLITS).reverse();
}
