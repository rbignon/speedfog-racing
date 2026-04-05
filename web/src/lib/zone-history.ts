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
 * Return `incoming` with `zone_history` restored from `previous` when the
 * incoming value has none. Used to preserve the locally-held history
 * across `leaderboard_update` / `player_update` messages that no longer
 * carry it (the server now transmits full history only in `race_state`
 * and emits incremental `zone_entered` events afterwards).
 *
 * Passes `incoming` through unchanged when it carries a zone_history or
 * when there is no previous history to restore from. Treats `undefined`
 * and `null` as "no history" (empty arrays are considered carried
 * history and are not overridden).
 */
export function preserveZoneHistory<
  T extends { zone_history: ZoneHistoryEntry[] | null },
>(incoming: T, previous: ZoneHistoryEntry[] | null | undefined): T {
  if (incoming.zone_history) return incoming;
  if (!previous) return incoming;
  return { ...incoming, zone_history: previous };
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
