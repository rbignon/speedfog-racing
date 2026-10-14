/** The desk clock: elapsed time since the race started, and time left to its deadline. */

function parts(ms: number): { h: number; m: number; s: number } {
  const total = Math.floor(Math.max(0, ms) / 1000);
  return {
    h: Math.floor(total / 3600),
    m: Math.floor((total % 3600) / 60),
    s: total % 60,
  };
}

const pad = (n: number) => n.toString().padStart(2, "0");

/** Wall clock since the race started, as the desk shows it. */
export function formatElapsed(ms: number): string {
  const { h, m, s } = parts(ms);
  return h > 0 ? `${h}:${pad(m)}:${pad(s)}` : `${m}:${pad(s)}`;
}

/** Time left before the race's own deadline, or null when it has none. */
export function formatCountdown(ms: number | null): string | null {
  if (ms === null) return null;
  return formatElapsed(ms);
}

/** Time left before the race's start, rounded up to the second about to tick,
 * as a countdown reads. */
export function formatStartsIn(ms: number): string {
  return formatElapsed(Math.ceil(Math.max(0, ms) / 1000) * 1000);
}

/**
 * The race status a cast scene shows at `nowMs` (the scene's own clock, its
 * `delay` already taken off). The server runs a race from the start command
 * on, its `started_at` a countdown later: until then the scene keeps its
 * pre-start look (no ranks, no leader, no map), so a race still counting
 * down shows as "setup". A running race with no known start, and every other
 * status, show as they are.
 */
export function sceneRaceStatus(
  status: string,
  startedAt: string | null,
  nowMs: number,
): string {
  if (status !== "running" || !startedAt) return status;
  return nowMs < Date.parse(startedAt) ? "setup" : status;
}
