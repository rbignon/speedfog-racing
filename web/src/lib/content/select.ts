import type { AuthUser } from "$lib/api";
import type { ContentItem } from "./types";

export const SEEN_STORAGE_KEY = "speedfog_tips_seen";
const SEEN_MAX = 40;
/** Played runs (races, dailies and solos together) past which a player is no longer a newcomer. */
export const EXPERIENCED_RUNS = 3;

export interface TickerContext {
  poolName?: string | null;
  seenIds: ReadonlySet<string>;
  /** Advanced tips edge out beginner ones instead of the reverse. */
  experienced?: boolean;
}

type PlayedCounts = Pick<
  AuthUser,
  "race_count" | "daily_count" | "training_count"
>;

/**
 * Whether the player has enough runs behind them to be served advanced tips
 * first. The counts ride on `/auth/me`; a user object cached before they
 * existed reads as a newcomer until the next refresh.
 */
export function isExperiencedPlayer(
  user: Partial<PlayedCounts> | null,
): boolean {
  if (!user) return false;
  const played =
    (user.race_count ?? 0) +
    (user.daily_count ?? 0) +
    (user.training_count ?? 0);
  return played >= EXPERIENCED_RUNS;
}

/**
 * Orders catalog items for the ticker: kind "skip" items and zone-scoped
 * items are never eligible (they belong to the zone codex, not the
 * pre-race/training rotation, and naming a zone before the race would hint
 * that it is in the seed), pool-specific items are dropped unless the pool
 * matches (and then float to the top), recently seen items sink, and tips of
 * the player's level (beginner by default, advanced once experienced) edge
 * out the others. Within a score tier the order is random, so two players
 * (or two visits) do not scroll the same sequence.
 */
export function orderTickerItems(
  items: ContentItem[],
  ctx: TickerContext,
  // Must return a value in [0, 1) like Math.random; 1 would index out of
  // bounds in the shuffle.
  rng: () => number = Math.random,
): ContentItem[] {
  // Fresh array from filter(), safe to shuffle in place below.
  const shuffled = items.filter(
    (item) =>
      item.kind !== "skip" &&
      item.zoneId === undefined &&
      (!item.pools || (!!ctx.poolName && item.pools.includes(ctx.poolName))),
  );

  const preferredLevel = ctx.experienced ? "advanced" : "beginner";
  const score = (item: ContentItem): number => {
    let s = 0;
    if (item.pools) s += 5;
    if (ctx.seenIds.has(item.id)) s -= 3;
    if (item.kind === "tip" && item.level === preferredLevel) s += 1;
    return s;
  };

  // Fisher-Yates first, then sort by score with ties broken by the shuffled
  // index: equal-score items keep their shuffled order, while the weighting
  // still dominates the shuffle.
  for (let i = shuffled.length - 1; i > 0; i--) {
    const j = Math.floor(rng() * (i + 1));
    [shuffled[i], shuffled[j]] = [shuffled[j], shuffled[i]];
  }

  return shuffled
    .map((item, index) => ({ item, index, score: score(item) }))
    .sort((a, b) => b.score - a.score || a.index - b.index)
    .map((entry) => entry.item);
}

export function loadSeenTipIds(
  storage: Pick<Storage, "getItem"> | null,
): Set<string> {
  if (!storage) return new Set();
  try {
    const raw = storage.getItem(SEEN_STORAGE_KEY);
    if (!raw) return new Set();
    const parsed: unknown = JSON.parse(raw);
    if (!Array.isArray(parsed)) return new Set();
    return new Set(parsed.filter((v): v is string => typeof v === "string"));
  } catch {
    return new Set();
  }
}

export function markTipSeen(
  storage: Pick<Storage, "getItem" | "setItem"> | null,
  id: string,
): void {
  if (!storage) return;
  try {
    const raw = storage.getItem(SEEN_STORAGE_KEY);
    const parsed: unknown = raw ? JSON.parse(raw) : [];
    const list = Array.isArray(parsed)
      ? parsed.filter((v): v is string => typeof v === "string")
      : [];
    const next = [...list.filter((v) => v !== id), id].slice(-SEEN_MAX);
    storage.setItem(SEEN_STORAGE_KEY, JSON.stringify(next));
  } catch {
    // Storage full or unavailable: seen tracking is best-effort.
  }
}
