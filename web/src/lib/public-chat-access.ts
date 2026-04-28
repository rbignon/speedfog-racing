/**
 * Frontend mirror of the server's `can_read_public_chat` predicate.
 *
 * The server is authoritative; this helper only drives the local UI
 * (locked pane, locked-reason copy, transition detection that fires
 * the `request_chat_history` pull). Keep in lockstep with
 * `server/speedfog_racing/services/chat_access.py` and the spec at
 * `docs/specs/2026-04-28-public-chat-lock-design.md` (matrix lines 60 to 75).
 */

export type RaceStatus = "setup" | "running" | "finished";

export type ParticipantStatus =
  | "registered"
  | "ready"
  | "playing"
  | "finished"
  | "abandoned";

export type RaceRole = "organizer" | "admin" | "caster" | "participant" | null;

export type PublicAccess = "locked" | "readable";

const PRIVILEGED_ROLES: ReadonlySet<RaceRole> = new Set<RaceRole>([
  "organizer",
  "admin",
  "caster",
]);

export interface PublicAccessInputs {
  raceStatus: RaceStatus;
  /** ISO datetime string from the server, or null when no late-join
   * window is configured / the race has not started yet. */
  registrationClosesAt: string | null;
  role: RaceRole;
  participantStatus: ParticipantStatus | null;
  now: Date;
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
  const { raceStatus, role, participantStatus } = inputs;

  if (raceStatus === "finished") return "readable";
  if (raceStatus !== "running") return "locked";
  if (role !== null && PRIVILEGED_ROLES.has(role)) return "readable";
  if (role === "participant" && !isActiveParticipant(participantStatus)) {
    return "readable";
  }
  if (
    !registrationOpenWindow(
      raceStatus,
      inputs.registrationClosesAt,
      inputs.now,
    ) &&
    !isActiveParticipant(participantStatus)
  ) {
    return "readable";
  }
  return "locked";
}

/**
 * Locked-reason copy. Returns the suggested string per the spec
 * (lines 154 to 158). Caller should only display the reason while
 * `computePublicAccess(...) === "locked"`.
 */
export function computePublicLockedReason(inputs: PublicAccessInputs): string {
  const { raceStatus, role, participantStatus } = inputs;

  if (raceStatus === "setup") {
    return "Public chat unlocks after the race starts and registration closes.";
  }

  // RUNNING from here. Active participant cases.
  if (role === "participant" && isActiveParticipant(participantStatus)) {
    return "Public chat unlocks when you finish.";
  }

  // Spectator (no role) during the late-join window.
  if (
    role === null &&
    registrationOpenWindow(raceStatus, inputs.registrationClosesAt, inputs.now)
  ) {
    return "Public chat unlocks when late join closes.";
  }

  // Fallback: covers any locked combination not enumerated above
  // (should not normally render; helper still returns a sensible string).
  return "Public chat is locked.";
}
