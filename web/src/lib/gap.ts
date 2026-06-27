/**
 * Client-side gap (delta to leader) logic, ported verbatim from the mod's
 * `compute_gap` (mod/src/core/format.rs) and the server's `compute_gap_ms`.
 *
 * The race store recomputes the gap live on every tick from the leader's
 * per-layer splits plus each player's layer entry IGT, so the web leaderboard
 * shows the same smooth LiveSplit-style gap as the in-game overlay rather than
 * the intermittent server snapshot.
 */

export interface GapInput {
  status: string;
  /** Player's current IGT in ms (live). */
  igtMs: number;
  currentLayer: number;
  /** IGT at which the player entered current_layer, or null if unknown. */
  layerEntryIgt: number | null;
  /** Leader's per-layer entry IGTs (layer -> igt_ms). */
  leaderSplits: Record<number, number>;
  /** Whether this player is the leader (rank 0): the leader has no gap. */
  isLeader: boolean;
  /** Leader's current IGT in ms. */
  leaderIgtMs: number;
  /** Whether the leader has finished (changes the last-layer exit time). */
  leaderFinished: boolean;
}

/**
 * Gap to the leader in ms (negative = ahead), or null when it is undefined:
 * the leader itself, a non-playing/non-finished status, or missing split data.
 */
export function computeGap(input: GapInput): number | null {
  const {
    status,
    igtMs,
    currentLayer,
    layerEntryIgt,
    leaderSplits,
    isLeader,
    leaderIgtMs,
    leaderFinished,
  } = input;

  if (isLeader) return null;
  if (status === "finished") return igtMs - leaderIgtMs;
  if (status !== "playing") return null;

  const leaderEntry = leaderSplits[currentLayer];
  if (leaderEntry === undefined || layerEntryIgt === null) return null;
  const entryDelta = layerEntryIgt - leaderEntry;

  // Leader's exit from this layer = leader's entry on the next layer.
  let leaderExit = leaderSplits[currentLayer + 1];
  if (leaderExit === undefined) {
    if (leaderFinished) {
      // Last layer: the leader has finished, use its finish IGT as exit time.
      leaderExit = leaderIgtMs;
    } else {
      // Leader hasn't left this layer yet: only the entry delta is known.
      return entryDelta;
    }
  }

  // Compare time spent in the layer, not absolute IGTs.
  const timeInLayer = igtMs - layerEntryIgt;
  const leaderTimeInLayer = leaderExit - leaderEntry;
  if (timeInLayer <= leaderTimeInLayer) return entryDelta;
  return entryDelta + (timeInLayer - leaderTimeInLayer);
}

/**
 * Format a gap in ms as `+M:SS` / `+H:MM:SS` (behind) or `-M:SS` / `-H:MM:SS`
 * (ahead). Mirrors the mod's `format_gap_into`.
 */
export function formatGap(ms: number): string {
  const sign = ms < 0 ? "-" : "+";
  const totalSeconds = Math.floor(Math.abs(ms) / 1000);
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = totalSeconds % 60;
  if (hours > 0) {
    return `${sign}${hours}:${minutes.toString().padStart(2, "0")}:${seconds.toString().padStart(2, "0")}`;
  }
  return `${sign}${minutes}:${seconds.toString().padStart(2, "0")}`;
}

/**
 * Format a gap with degressive precision for the web leaderboard page:
 * precise when small (seconds matter), coarse when large (they do not).
 *
 *   < 10 min -> `+M:SS`  (+0:49, +9:59)
 *   < 1 h    -> `+Mm`    (+11m, +33m)
 *   >= 1 h   -> `+HhMM`  (+1h05)
 *
 * Intentionally web-leaderboard only: it DIVERGES from `formatGap` (the
 * verbatim mod port shared with the OBS overlay), which keeps `+H:MM:SS`.
 */
export function formatGapCompact(ms: number): string {
  const sign = ms < 0 ? "-" : "+";
  const totalSeconds = Math.floor(Math.abs(ms) / 1000);
  const minutes = Math.floor(totalSeconds / 60);
  if (minutes < 10) {
    return `${sign}${minutes}:${(totalSeconds % 60).toString().padStart(2, "0")}`;
  }
  if (minutes < 60) {
    return `${sign}${minutes}m`;
  }
  const hours = Math.floor(minutes / 60);
  return `${sign}${hours}h${(minutes % 60).toString().padStart(2, "0")}`;
}
