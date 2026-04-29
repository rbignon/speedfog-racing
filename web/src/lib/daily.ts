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

/**
 * Short status label for the Daily card / nav dot.
 *
 * Reads the ``my_*`` fields populated by ``race_response`` for the
 * authenticated user. Works on either ``Race`` summaries (home, dashboard)
 * or ``RaceDetail`` since both share the same fields.
 */
export function dailyUserStatus(
  race: Pick<Race, "my_role" | "my_participant_status" | "my_igt_ms">,
): string {
  if (race.my_role !== "participating" || !race.my_participant_status) {
    return "Not played yet";
  }
  if (race.my_participant_status === "playing") return "Playing";
  if (race.my_participant_status === "abandoned") return "Abandoned";
  if (race.my_participant_status === "finished") {
    return `Finished in ${formatIgt(race.my_igt_ms ?? 0)}`;
  }
  return "Not started";
}

/** First-placed finisher in a race preview, or null if nobody finished. */
export function dailyWinner(
  race: Pick<Race, "participant_previews">,
): ParticipantPreview | null {
  const winner = race.participant_previews.find(
    (p) => p.placement === 1 && p.status === "finished",
  );
  return winner ?? null;
}

/**
 * Short result label for ``userId`` on a recent daily preview.
 * Returns null when the user has no preview row (didn't play or
 * finished outside the top-5 preview window).
 */
export function dailyUserResultPreview(
  race: Pick<Race, "participant_previews">,
  userId: string | null | undefined,
): string | null {
  if (!userId) return null;
  const preview = race.participant_previews.find((p) => p.id === userId);
  if (!preview) return null;
  if (preview.status === "finished" && preview.igt_ms != null) {
    const placement = preview.placement ? ` (#${preview.placement})` : "";
    return `${formatIgt(preview.igt_ms)}${placement}`;
  }
  if (preview.status === "abandoned") return "Abandoned";
  if (preview.status === "playing") return "Playing";
  return "Registered";
}

/** "Closes in 5h 23m" string for an absolute end timestamp. */
export function dailyCloseLabel(
  raceEndsAt: string | null,
  now: number,
): string | null {
  if (!raceEndsAt) return null;
  const remainingMs = Math.max(0, new Date(raceEndsAt).getTime() - now);
  const hours = Math.floor(remainingMs / 3_600_000);
  const minutes = Math.floor((remainingMs % 3_600_000) / 60_000);
  return `Closes in ${hours}h ${minutes}m`;
}
