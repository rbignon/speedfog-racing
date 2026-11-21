/**
 * Relay races: teams of runners share one run, one playing at a time.
 */

import type { RelayTeam } from "$lib/api";

export const RELAY_TEAM_SIZE_MIN = 2;
export const RELAY_TEAM_SIZE_MAX = 6;

/** Whether a team size is one the server accepts: an integer from 2 to 6
 * (a cleared number input binds `null`). */
export function isValidRelayTeamSize(size: number | null | undefined): boolean {
  return (
    typeof size === "number" &&
    Number.isInteger(size) &&
    size >= RELAY_TEAM_SIZE_MIN &&
    size <= RELAY_TEAM_SIZE_MAX
  );
}

/** Zones one runner may play: `ceil(total_layers / members) + 1`, as the
 * server computes it (a team with no active member counts as one). */
export function relayCap(totalLayers: number, activeMembers: number): number {
  return Math.ceil(totalLayers / Math.max(1, activeMembers)) + 1;
}

/** The cap on a runner's zones for a team size, as a sentence; null when the
 * pool gives no zone count. */
export function relayCapSentence(
  totalLayers: number | null | undefined,
  teamSize: number | null | undefined,
): string | null {
  if (!totalLayers || totalLayers <= 0) return null;
  if (!isValidRelayTeamSize(teamSize)) return null;
  return `${totalLayers} zones, teams of ${teamSize}: ${relayCap(totalLayers, teamSize as number)} zones max per runner.`;
}

/** What a team's dashed button offers the viewer: "join" the race into it,
 * "move" there from their own team, or nothing (their own team, a full team,
 * or someone who cannot register). `canRegister` is whether the viewer may
 * take a seat at all (logged in, not the caster or the non-playing organizer,
 * setup). */
export function teamSlotAction(
  team: RelayTeam,
  teamSize: number,
  viewer: { participantTeamId: string | null; canRegister: boolean },
): "join" | "move" | null {
  if (!viewer.canRegister) return null;
  if (team.member_ids.length >= teamSize) return null;
  if (viewer.participantTeamId === team.id) return null;
  return viewer.participantTeamId ? "move" : "join";
}

/** The participant count the header can show as a maximum: teams x size once
 * runners cannot create teams (the race is full when they are), else the
 * open-registration maximum, else null (no maximum). */
export function relayCapacity(
  teams: RelayTeam[],
  teamSize: number,
  runnersCreateTeams: boolean,
  maxParticipants: number | null,
): number | null {
  return runnersCreateTeams ? maxParticipants : teams.length * teamSize;
}

/** Why a relay race cannot start yet, with the server's texts
 * (`relay_start_error`), or null. Teams with no member are ignored; a runner
 * counts when their status is "ready". */
export function relayStartBlocker(
  teams: RelayTeam[],
  statusById: Record<string, string>,
): string | null {
  const counting = teams.filter((t) => t.member_ids.length > 0);
  if (counting.length < 2) {
    return "At least 2 teams are required to start a relay race";
  }
  for (const t of counting) {
    const ready = t.member_ids.filter(
      (id) => statusById[id] === "ready",
    ).length;
    if (ready < RELAY_TEAM_SIZE_MIN) {
      return `${t.name} needs at least ${RELAY_TEAM_SIZE_MIN} ready runners`;
    }
  }
  return null;
}

/** The runner who starts: the chosen one while they are still a member, else
 * the first member registered. */
export function startingRunnerId(team: RelayTeam): string | null {
  if (team.first_runner_id && team.member_ids.includes(team.first_runner_id)) {
    return team.first_runner_id;
  }
  return team.member_ids[0] ?? null;
}

/** The participants grouped by team, in team order, each team's members in
 * the team's own order. A participant no team lists is left out. */
export function teamView<P extends { id: string }>(
  teams: RelayTeam[],
  participants: P[],
): { team: RelayTeam; members: P[] }[] {
  const byId = new Map(participants.map((p) => [p.id, p]));
  return teams.map((team) => ({
    team,
    members: team.member_ids.flatMap((id) => {
      const p = byId.get(id);
      return p ? [p] : [];
    }),
  }));
}

/** The value of the "New team" entry in a team select. */
export const NEW_TEAM = "new";

/** The entries of a team select for someone about to join: the teams with a
 * free slot ("Name (members/size)"), then "New team" when allowed. */
export function teamChoiceOptions(
  teams: RelayTeam[],
  teamSize: number,
  canCreate: boolean,
): { value: string; label: string }[] {
  const options = teams
    .filter((t) => t.member_ids.length < teamSize)
    .map((t) => ({
      value: t.id,
      label: `${t.name} (${t.member_ids.length}/${teamSize})`,
    }));
  if (canCreate) options.push({ value: NEW_TEAM, label: "New team" });
  return options;
}

/** The request body a select value stands for. */
export function relayChoiceFor(value: string): {
  relay_team_id?: string;
  create_team?: boolean;
} {
  return value === NEW_TEAM ? { create_team: true } : { relay_team_id: value };
}
