/**
 * Utilities for the client-side zone_history store.
 *
 * The server no longer sends full zone_history in leaderboard_update /
 * player_update broadcasts. Instead, the client bootstraps from
 * race_state and applies incremental zone_entered events.
 */

export interface ZoneHistoryEntry {
  node_id: string;
  igt_ms: number;
  deaths?: number;
  type?: string;
}

/**
 * Upsert a zone_history entry keyed by (node_id, igt_ms).
 *
 * - When no entry with the same key exists: appends it.
 * - When one exists: replaces it in place (e.g. deaths updated via
 *   server-side attribute_deaths).
 *
 * The (node_id, igt_ms) pair is unique per entry: igt_ms strictly
 * increases for fresh zone entries, and the server re-emits the
 * original igt_ms when updating deaths on an existing entry.
 */
export function upsertZoneHistoryEntry(
  history: ZoneHistoryEntry[] | null,
  entry: ZoneHistoryEntry,
): ZoneHistoryEntry[] {
  const current = history ?? [];
  const idx = current.findIndex(
    (e) => e.node_id === entry.node_id && e.igt_ms === entry.igt_ms,
  );
  if (idx === -1) {
    return [...current, entry];
  }
  const next = [...current];
  next[idx] = entry;
  return next;
}
