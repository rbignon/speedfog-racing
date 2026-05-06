/**
 * Helpers shared across the Daily Seed surfaces (week grid, archive page).
 * Kept thin: each helper is a pure projection over the existing Race /
 * RaceDetail types so component code reads the same shape regardless of
 * where it was loaded from.
 */

import type {
  DailyWeekDay,
  DailyWeekResponse,
  Participant,
  ParticipantStatus,
  Race,
  RaceDetail,
} from "$lib/api";
import { formatPoolName } from "$lib/utils/format";
import type { WsParticipant } from "$lib/websocket";

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

/**
 * Patch the day cell whose ``date`` matches ``opts.date`` with values derived
 * from the live WebSocket participant list, leaving every other cell
 * untouched. Used by ``/daily/[date]`` so the in-page DailyWeekGrid mirrors
 * the live race that page is already subscribed to (participants joining,
 * the viewer's own status, the live placement once they finish). Surfaces
 * without a WebSocket subscription (``/``, ``/dashboard``) keep using the
 * server snapshot directly.
 *
 * Pure: returns a new object only when the matched day's projected fields
 * actually differ, otherwise the original ``week`` reference is returned so
 * downstream ``$effect`` / memoization can short-circuit.
 */
export function applyLiveDailyDayUpdate(
  week: DailyWeekResponse,
  opts: {
    date: string;
    participants: WsParticipant[];
    myParticipantId: string | null;
  },
): DailyWeekResponse {
  const idx = week.days.findIndex((d) => d.date === opts.date);
  if (idx === -1) return week;
  const day = week.days[idx];
  // Only race-backed cells carry counts / podium / my_result; "future" and
  // "missing_past" cells have no race to mirror.
  if (day.state !== "today" && day.state !== "past") return week;

  const patched = patchDayFromLive(
    day,
    opts.participants,
    opts.myParticipantId,
  );
  if (patched === day) return week;
  const days = [...week.days];
  days[idx] = patched;
  return { ...week, days };
}

function patchDayFromLive(
  day: DailyWeekDay,
  participants: WsParticipant[],
  myParticipantId: string | null,
): DailyWeekDay {
  const participantsCount = participants.length;
  const startersCount = participants.reduce(
    (n, p) => (p.igt_ms > 0 ? n + 1 : n),
    0,
  );
  const myResult = buildLiveMyResult(
    participants,
    myParticipantId,
    startersCount,
  );

  if (
    day.participants_count === participantsCount &&
    day.starters_count === startersCount &&
    myResultEquals(day.my_result, myResult)
  ) {
    return day;
  }

  return {
    ...day,
    participants_count: participantsCount,
    starters_count: startersCount,
    my_result: myResult,
  };
}

function buildLiveMyResult(
  participants: WsParticipant[],
  myParticipantId: string | null,
  startersCount: number,
): DailyWeekDay["my_result"] {
  if (!myParticipantId) return null;
  const me = participants.find((p) => p.id === myParticipantId);
  if (!me) return null;
  const status = me.status as ParticipantStatus;
  let placement: number | null = null;
  if (status === "finished") {
    // The server tiebreaks finishers by (igt_ms, finished_at); WsParticipant
    // does not carry finished_at, so on a millisecond IGT tie the live
    // placement may flicker until the next /daily/week snapshot lands.
    const finishers = participants
      .filter((p) => p.status === "finished")
      .sort((a, b) => a.igt_ms - b.igt_ms);
    const pos = finishers.findIndex((p) => p.id === me.id);
    placement = pos >= 0 ? pos + 1 : null;
  }
  return {
    status,
    placement,
    total_starters: startersCount,
    igt_ms: status === "finished" ? me.igt_ms : null,
    death_count: me.death_count,
  };
}

function myResultEquals(
  a: DailyWeekDay["my_result"],
  b: DailyWeekDay["my_result"],
): boolean {
  if (a === b) return true;
  if (a === null || b === null) return false;
  return (
    a.status === b.status &&
    a.placement === b.placement &&
    a.total_starters === b.total_starters &&
    a.igt_ms === b.igt_ms &&
    a.death_count === b.death_count
  );
}
