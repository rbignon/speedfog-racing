/**
 * Cheat detection: the game debug flags a runner's mod saw during a race
 * (see docs/CHEAT_DETECTION.md). Shown to the race organizer and admins
 * only.
 */
import type { DebugFlags, Participant } from "$lib/api";

// Keep in sync with DEBUG_FLAGS in mod/src/core/debug_flags.rs and
// DEBUG_FLAG_LABELS in server/speedfog_racing/services/debug_flags.py.
const LABELS: Record<string, string> = {
  player_no_death: "Player no death",
  torrent_no_death: "Torrent no death",
  one_shot: "One shot",
  infinite_consumables: "Infinite consumables",
  infinite_stamina: "Infinite stamina",
  infinite_fp: "Infinite FP",
  infinite_arrows: "Infinite arrows",
  hidden: "Hidden",
  silent: "Silent",
  all_no_death: "No death (all)",
  all_no_damage: "No damage (all)",
  all_no_hit: "No hit (all)",
  all_no_attack: "No attack (all)",
  all_no_move: "No move (all)",
  all_no_ai: "AI off (all)",
  infinite_aow_fp: "Infinite FP (Ashes of War)",
};

export function debugFlagLabel(name: string): string {
  return LABELS[name] ?? name;
}

/**
 * Detections by participant id: the REST snapshot, with each live
 * `debug_flags_detected` payload replacing that participant's whole map.
 */
export function mergeDebugFlags(
  participants: Participant[],
  live: Record<string, DebugFlags>,
): Record<string, DebugFlags> {
  const merged: Record<string, DebugFlags> = {};
  for (const p of participants) {
    if (p.debug_flags) merged[p.id] = p.debug_flags;
  }
  return { ...merged, ...live };
}

export interface DetectionFlag {
  name: string;
  label: string;
  igtMs: number;
  nodeId: string | null;
}

export interface DetectionRow {
  participantId: string;
  flags: DetectionFlag[];
}

/** One row per flagged runner; flags and rows in order of first observation. */
export function detectionRows(
  detections: Record<string, DebugFlags>,
): DetectionRow[] {
  return Object.entries(detections)
    .map(([participantId, flags]) => ({
      participantId,
      flags: Object.entries(flags)
        .map(([name, o]) => ({
          name,
          label: debugFlagLabel(name),
          igtMs: o.igt_ms,
          nodeId: o.node_id,
        }))
        .sort((a, b) => a.igtMs - b.igtMs),
    }))
    .filter((row) => row.flags.length > 0)
    .sort((a, b) => a.flags[0].igtMs - b.flags[0].igtMs);
}
