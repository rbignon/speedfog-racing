import type { WsParticipant } from "$lib/websocket";

/** What a log row reports: a zone entered, or how the runner's race ended. */
export type CastLogKind = "zone" | "finish" | "dnf" | "dq";

/** One zone_history entry, resolved to a display name and a runner, or the
 * runner's outcome. */
export interface CastLogRow {
  id: string;
  kind: CastLogKind;
  name: string;
  colorIndex: number;
  /** The zone entered; empty on an outcome row. */
  zone: string;
  igtMs: number;
  deaths?: number;
}

const OUTCOMES: Partial<Record<string, Exclude<CastLogKind, "zone">>> = {
  finished: "finish",
  abandoned: "dnf",
  disqualified: "dq",
};

/**
 * Flatten every participant's zone_history into a single feed, newest
 * first, capped to `limit` rows.
 *
 * `zone_history` entries carry only `node_id` and `igt_ms` (see
 * `ZoneHistoryEntry` in `$lib/zone-history`); there is no zone name on the
 * wire. `nodeNames` is the seed's own node id -> label name map (see
 * `parseDagGraph`, `DagNode.labelName`), the same one the quad and focus
 * scenes build from `raceStore.seed.graph_json`. A miss falls back to the
 * raw node id rather than an empty string: unlike a card's current-zone line
 * (which would rather show nothing than a raw id for a moment), a log row
 * that names no runner activity at all reads as broken, not as "not yet
 * resolved".
 *
 * A `zone_history` of `null` means that participant's history has not
 * arrived yet and contributes no rows.
 *
 * A runner whose race is over (finished, DNF, among them an IGT cutoff, or
 * DQ) also gets one outcome row at their own `igt_ms`: zone_history carries
 * none of these, and they are the moments a caster most needs on the feed.
 */
export function buildCastLog(
  participants: Pick<
    WsParticipant,
    | "id"
    | "twitch_username"
    | "twitch_display_name"
    | "color_index"
    | "status"
    | "igt_ms"
    | "zone_history"
  >[],
  nodeNames: Map<string, string>,
  limit: number,
): CastLogRow[] {
  const rows: CastLogRow[] = [];
  for (const p of participants) {
    if (!p.zone_history) continue;
    const name = p.twitch_display_name || p.twitch_username;
    const outcome = OUTCOMES[p.status];
    if (outcome) {
      rows.push({
        id: p.id,
        kind: outcome,
        name,
        colorIndex: p.color_index,
        zone: "",
        igtMs: p.igt_ms,
      });
    }
    for (const entry of p.zone_history) {
      rows.push({
        id: p.id,
        kind: "zone",
        name,
        colorIndex: p.color_index,
        zone: nodeNames.get(entry.node_id) ?? entry.node_id,
        igtMs: entry.igt_ms,
        deaths: entry.deaths,
      });
    }
  }
  // At equal times an outcome goes first: a finish lands on the entry's
  // own tick, and it is the line the caster is after.
  const isZone = (r: CastLogRow) => (r.kind === "zone" ? 1 : 0);
  rows.sort((a, b) => b.igtMs - a.igtMs || isZone(a) - isZone(b));
  return rows.slice(0, limit);
}
