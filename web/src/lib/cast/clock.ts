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
