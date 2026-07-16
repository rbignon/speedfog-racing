/**
 * Frontend mirror of the server's `can_read_public_chat` predicate.
 *
 * The server is authoritative; this helper only drives the local UI
 * (locked pane, locked-reason copy, transition detection that fires
 * the `request_chat_history` pull). Keep in lockstep with
 * `server/speedfog_racing/services/chat_access.py` and the public-channel
 * access matrix in the "Chat System" section of `docs/PROTOCOL.md`.
 */

import type { ParticipantStatus, RaceStatus } from "$lib/api";

export type PublicAccess = "locked" | "readable";

export interface PublicAccessInputs {
  raceStatus: RaceStatus;
  /** ISO datetime string from the server, or null when no late-join
   * window is configured / the race has not started yet. */
  registrationClosesAt: string | null;
  /** Status of the viewer's own participation, or null if the viewer
   * is not a participant. Race role (organizer/admin/caster) does not
   * influence public-chat access by itself. */
  participantStatus: ParticipantStatus | null;
  now: Date;
  /** True for Daily Seed pages. Only changes the locked-reason copy:
   * on a daily, "late join closes" coincides with "the daily ends"
   * (both windows are 24h), so the race-flavored phrasing is misleading. */
  isDaily?: boolean;
}

function isActiveParticipant(status: ParticipantStatus | null): boolean {
  if (status === null) return false;
  return status !== "finished" && status !== "abandoned";
}

function registrationOpenWindow(
  raceStatus: RaceStatus,
  registrationClosesAt: string | null,
  now: Date,
): boolean {
  if (raceStatus === "setup") return true;
  if (raceStatus !== "running") return false;
  if (registrationClosesAt === null) return false;
  return now.getTime() < new Date(registrationClosesAt).getTime();
}

export function computePublicAccess(inputs: PublicAccessInputs): PublicAccess {
  const { raceStatus, participantStatus } = inputs;

  if (raceStatus === "finished") return "readable";
  if (raceStatus !== "running") return "locked";
  if (isActiveParticipant(participantStatus)) {
    // Active racer: locked until they finish or abandon.
    return "locked";
  }
  if (participantStatus !== null) {
    // Finished or abandoned participant: unlocked even while the
    // late-join window is still open.
    return "readable";
  }
  // Non-participant viewer (spectator or any race role not also
  // playing): unlocked only once the late-join window has closed.
  return registrationOpenWindow(
    raceStatus,
    inputs.registrationClosesAt,
    inputs.now,
  )
    ? "locked"
    : "readable";
}

/**
 * Locked-reason copy. Returns the suggested string per the spec
 * (lines 154 to 158). Caller should only display the reason while
 * `computePublicAccess(...) === "locked"`.
 */
export function computePublicLockedReason(inputs: PublicAccessInputs): string {
  const { raceStatus, participantStatus } = inputs;

  if (raceStatus === "setup") {
    return "Public chat unlocks after the race starts and registration closes.";
  }

  // RUNNING from here. Active racers wait for their own finish.
  if (isActiveParticipant(participantStatus)) {
    return "Public chat unlocks when you finish.";
  }

  // Everyone else who is locked is waiting for the late-join window
  // to close (spectators and any non-playing privileged role).
  if (
    registrationOpenWindow(raceStatus, inputs.registrationClosesAt, inputs.now)
  ) {
    return inputs.isDaily
      ? "Public chat unlocks once the daily ends."
      : "Public chat unlocks when late join closes.";
  }

  // Fallback: covers any locked combination not enumerated above
  // (should not normally render; helper still returns a sensible string).
  return "Public chat is locked.";
}
