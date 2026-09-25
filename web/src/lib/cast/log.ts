import type { WsParticipant } from "$lib/websocket";

/** One zone_history entry, resolved to a display name and a runner. */
export interface CastLogRow {
  id: string;
  name: string;
  colorIndex: number;
  zone: string;
  igtMs: number;
  deaths?: number;
}

/**
 * Flatten every participant's zone_history into a single feed, newest
 * first, capped to `limit` rows.
 *
 * `zone_history` entries carry only `node_id` and `igt_ms` (see
 * `ZoneHistoryEntry` in `$lib/zone-history`); there is no zone name on the
 * wire. `nodeNames` is the seed's own node id -> display name map (see
 * `parseDagGraph`), the same one the quad and focus scenes build from
 * `raceStore.seed.graph_json`. A miss falls back to the raw node id rather
 * than an empty string: unlike a card's current-zone line (which would
 * rather show nothing than a raw id for a moment), a log row that names no
 * runner activity at all reads as broken, not as "not yet resolved".
 *
 * A `zone_history` of `null` means that participant's history has not
 * arrived yet and contributes no rows.
 */
export function buildCastLog(
  participants: Pick<
    WsParticipant,
    | "id"
    | "twitch_username"
    | "twitch_display_name"
    | "color_index"
    | "zone_history"
  >[],
  nodeNames: Map<string, string>,
  limit: number,
): CastLogRow[] {
  const rows: CastLogRow[] = [];
  for (const p of participants) {
    if (!p.zone_history) continue;
    const name = p.twitch_display_name || p.twitch_username;
    for (const entry of p.zone_history) {
      rows.push({
        id: p.id,
        name,
        colorIndex: p.color_index,
        zone: nodeNames.get(entry.node_id) ?? entry.node_id,
        igtMs: entry.igt_ms,
        deaths: entry.deaths,
      });
    }
  }
  rows.sort((a, b) => b.igtMs - a.igtMs);
  return rows.slice(0, limit);
}
