/** Everything a cast scene reads from its URL. */
export interface CastParams {
  /** Twitch usernames wanted in slots 1 to 4, null where the URL is silent. */
  slots: (string | null)[];
  cams: number;
  casters: [string | null, string | null];
  delayMs: number;
  focus: number;
  guides: boolean;
  /** The event slug the co-brand is drawn from, null off an event. */
  event: string | null;
}

/** Longest delay a caster can plausibly be running behind, in seconds. */
const MAX_DELAY_S = 60;

function clampInt(
  raw: string | null,
  min: number,
  max: number,
  fallback: number,
): number {
  if (raw === null || raw === "") return fallback;
  const n = Number.parseInt(raw, 10);
  if (Number.isNaN(n)) return fallback;
  return Math.min(max, Math.max(min, n));
}

export function parseCastParams(url: URL): CastParams {
  const q = url.searchParams;
  return {
    slots: [1, 2, 3, 4].map((i) => q.get(`p${i}`) || null),
    cams: clampInt(q.get("cams"), 0, 2, 2),
    casters: [q.get("c1") || null, q.get("c2") || null],
    delayMs: clampInt(q.get("delay"), 0, MAX_DELAY_S, 0) * 1000,
    focus: clampInt(q.get("focus"), 1, 4, 1),
    guides: q.get("guides") === "1",
    event: q.get("event") || null,
  };
}

/**
 * Seat the runners: a named slot takes that runner, the slots left open take
 * the runners nobody named, in join order. Join order is the default on
 * purpose: the live ranking moves during the race, and a hole that changed
 * runner mid-race would name the wrong player over someone else's video.
 * The fallback pool is sorted by `color_index`, which the server assigns as
 * max + 1 when a runner joins, so it is join order by construction. Callers
 * pass the live leaderboard, which is ordered by rank, so sorting here is what
 * keeps a hole from re-seating itself when the standings move.
 */
export function resolveSlots<
  T extends { twitch_username: string; color_index: number },
>(participants: T[], wanted: (string | null)[]): (T | null)[] {
  const seated: (T | null)[] = [null, null, null, null];
  const taken = new Set<T>();

  wanted.slice(0, 4).forEach((name, i) => {
    if (!name) return;
    const match = participants.find(
      (p) =>
        p.twitch_username.toLowerCase() === name.toLowerCase() && !taken.has(p),
    );
    if (match) {
      seated[i] = match;
      taken.add(match);
    }
  });

  const rest = participants
    .filter((p) => !taken.has(p))
    .sort((a, b) => a.color_index - b.color_index);
  for (let i = 0; i < seated.length; i++) {
    if (seated[i] === null && wanted[i] == null) {
      seated[i] = rest.shift() ?? null;
    }
  }
  return seated;
}
