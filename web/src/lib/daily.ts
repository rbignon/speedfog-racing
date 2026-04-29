/**
 * Helpers shared across the Daily Seed surfaces (week grid, archive page).
 * Kept thin: each helper is a pure projection over the existing Race /
 * RaceDetail types so component code reads the same shape regardless of
 * where it was loaded from.
 */

import type { Participant, Race, RaceDetail } from "$lib/api";
import { formatPoolName } from "$lib/utils/format";

/** Build the archive route for a given rotation date (YYYY-MM-DD). */
export function dailyPathForDate(date: string): string {
  return `/daily/${date}`;
}

/** Localized "Daily Seed - Monday, April 27, 2026" style title for a rotation date. */
export function dailyTitle(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  return `Daily Seed - ${parsed.toLocaleDateString(undefined, {
    weekday: "long",
    month: "long",
    day: "numeric",
    year: "numeric",
    timeZone: "UTC",
  })}`;
}

/** Title-cased pool name, or "Unknown" if no pool was assigned yet. */
export function dailyTheme(race: Pick<Race, "pool_name">): string {
  return race.pool_name ? formatPoolName(race.pool_name) : "Unknown";
}

/** Find the participant matching ``userId`` (or null when not playing). */
export function currentUserParticipant(
  race: RaceDetail,
  userId: string | null | undefined,
): Participant | null {
  if (!userId) return null;
  return race.participants.find((p) => p.user.id === userId) ?? null;
}
