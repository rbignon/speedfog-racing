/**
 * Utilities for the client-side zone_history store.
 *
 * The server no longer sends full zone_history in leaderboard_update /
 * player_update broadcasts. Instead, the client bootstraps from
 * race_state and applies zone_history snapshot messages (full list,
 * self-healing).
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
 * and in `zone_history` snapshot messages).
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
