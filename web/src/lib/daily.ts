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
 * Returns the original ``week`` reference when the matched day's projected
 * fields are unchanged, so downstream $derived consumers can short-circuit
 * on identity instead of re-rendering on every WS frame.
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

  const prev = day.my_result;
  const myResultUnchanged =
    prev === myResult ||
    (prev !== null &&
      myResult !== null &&
      prev.status === myResult.status &&
      prev.placement === myResult.placement &&
      prev.total_starters === myResult.total_starters &&
      prev.igt_ms === myResult.igt_ms &&
      prev.death_count === myResult.death_count &&
      prev.qualifies === myResult.qualifies);

  if (
    day.participants_count === participantsCount &&
    day.starters_count === startersCount &&
    myResultUnchanged
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
    // Server tiebreaks finishers by (igt_ms, finished_at); WsParticipant has
    // no finished_at, so on a millisecond IGT tie the live placement may
    // flicker until the next /daily/week snapshot lands.
    const finishers = participants
      .filter((p) => p.status === "finished")
      .sort((a, b) => a.igt_ms - b.igt_ms);
    const pos = finishers.findIndex((p) => p.id === me.id);
    placement = pos >= 0 ? pos + 1 : null;
  }
  // Mirror the server rule: qualifies iff the participant has visited at
  // least two zones. zone_history may be null on the WS payload when the
  // mod has not pushed it yet, which is treated as not-yet-qualifying.
  const qualifies = (me.zone_history?.length ?? 0) >= 2;
  return {
    status,
    placement,
    total_starters: startersCount,
    igt_ms: status === "finished" ? me.igt_ms : null,
    death_count: me.death_count,
    qualifies,
  };
}
