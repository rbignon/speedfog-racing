/**
 * Helpers shared across the Daily Seed surfaces (banner, dashboard,
 * archive page). Kept thin: each helper is a pure projection over the
 * existing Race / RaceDetail / ParticipantPreview types so component
 * code reads the same shape regardless of where it was loaded from.
 */

import type {
  Participant,
  ParticipantPreview,
  Race,
  RaceDetail,
} from "$lib/api";
import { formatPoolName } from "$lib/utils/format";
import { formatIgt } from "$lib/utils/training";

/** Build the archive route for a given rotation date (YYYY-MM-DD). */
export function dailyPathForDate(date: string): string {
  return `/daily/${date}`;
}

/**
 * Lowest IGT among finished participants in a leaderboard preview.
 * Returns ``null`` when nobody has finished yet — callers are expected
 * to render a placeholder in that case.
 */
export function fastestFinishedIgt(
  previews: Pick<ParticipantPreview, "status" | "igt_ms">[],
): number | null {
  const times = previews
    .filter((p) => p.status === "finished" && p.igt_ms != null)
    .map((p) => p.igt_ms as number);
  return times.length ? Math.min(...times) : null;
}

/** Localized "Daily Seed - April 27, 2026" style title for a rotation date. */
export function dailyTitle(date: string): string {
  const parsed = new Date(`${date}T00:00:00Z`);
  return `Daily Seed - ${parsed.toLocaleDateString(undefined, {
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

/** Short status label for the Daily card / nav dot. */
export function dailyUserStatus(
  race: RaceDetail,
  userId: string | null | undefined,
): string {
  const participant = currentUserParticipant(race, userId);
  if (!participant) return "Not played yet";
  if (participant.status === "playing") return "Playing";
  if (participant.status === "abandoned") return "Abandoned";
  if (participant.status === "finished") {
    return `Finished in ${formatIgt(participant.igt_ms)}`;
  }
  return "Not started";
}
