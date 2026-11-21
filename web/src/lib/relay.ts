/**
 * Relay races: teams of runners share one run, one playing at a time.
 */

import type { RelayTeam } from "$lib/api";
import type { RelayMember, WsParticipant } from "$lib/websocket";
import type { ZoneHistoryEntry } from "$lib/zone-history";

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
 * (`relay_start_error`), or null. Teams with no member are ignored; each other
 * team needs its first runner "ready" (its other members need not be). */
export function relayStartBlocker(
  teams: RelayTeam[],
  statusById: Record<string, string>,
): string | null {
  const counting = teams.filter((t) => t.member_ids.length > 0);
  if (counting.length < 2) {
    return "At least 2 teams are required to start a relay race";
  }
  for (const t of counting) {
    const first = t.first_runner_id;
    if (first === null || !t.member_ids.includes(first)) {
      return `${t.name} has no first runner`;
    }
    if (statusById[first] !== "ready") {
      return `${t.name}'s first runner is not ready`;
    }
  }
  return null;
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

/** A live row as the leaderboard delivers it: a runner on a solo race, a team
 * (id = team id, `relay_members` set) on a relay race. */
interface LiveRow {
  id: string;
  twitch_username: string;
  status: string;
  relay_members?: { participant_id: string; status: string }[] | null;
}

/** The viewer's own live row: on a relay race the row of the team listing
 * their participant id, else the row with their username (a solo race). */
export function ownLiveRow<R extends LiveRow>(
  rows: R[],
  participantId: string,
  username: string,
): R | null {
  const team = rows.find((r) =>
    r.relay_members?.some((m) => m.participant_id === participantId),
  );
  return team ?? rows.find((r) => r.twitch_username === username) ?? null;
}

/** The status that says whether the viewer's run is on: a relay member who is
 * out (abandoned, disqualified) while their team plays on is out; otherwise
 * the row's own status. */
export function ownRunStatus(
  row: LiveRow | null,
  participantId: string,
): string | undefined {
  const own = row?.relay_members?.find(
    (m) => m.participant_id === participantId,
  );
  if (own && (own.status === "abandoned" || own.status === "disqualified")) {
    return own.status;
  }
  return row?.status;
}

/** What is known per runner (a cheat detection, a disqualification reason),
 * keyed by the id of the live row that shows it: the runner's team on a relay
 * race, whose rows are teams, the runner otherwise. Teammates share a row: the
 * first entry wins. A runner the race does not list keeps their own key. */
export function byLiveRow<T>(
  byParticipant: Record<string, T>,
  participants: { id: string; relay_team_id?: string | null }[],
): Record<string, T> {
  const rowOf = new Map(participants.map((p) => [p.id, p.relay_team_id]));
  const byRow: Record<string, T> = {};
  for (const [id, value] of Object.entries(byParticipant)) {
    const row = rowOf.get(id) ?? id;
    if (!(row in byRow)) byRow[row] = value;
  }
  return byRow;
}

/** Whether a replacement of the live rows needs the REST race re-fetched.
 * A solo race: when the runner ids differ from the REST ones. A relay race in
 * setup: always (every team change is broadcast, and the rows hold teams, not
 * the team list). A relay race otherwise: when the members the teams list
 * differ from the REST participants. Nothing before the race has loaded. */
export function needsRaceRefetch(input: {
  isRelay: boolean;
  raceStatus: string;
  loaded: boolean;
  rows: { id: string; relay_members?: { participant_id: string }[] | null }[];
  restIds: string[];
}): boolean {
  const { isRelay, raceStatus, loaded, rows, restIds } = input;
  if (isRelay && raceStatus === "setup") return loaded;
  if (rows.length === 0) return false;
  const liveIds = new Set(
    isRelay
      ? rows.flatMap((r) =>
          (r.relay_members ?? []).map((m) => m.participant_id),
        )
      : rows.map((r) => r.id),
  );
  const rest = new Set(restIds);
  return liveIds.size !== rest.size || [...liveIds].some((id) => !rest.has(id));
}

/** The second line of a playing team's row: "<holder>, <zone>" ("<holder>"
 * without a zone), "<holder> offline" when the holder has no connection,
 * "Baton free" when nobody holds the baton. Null for a row that is not a team
 * and for a team that is not playing. */
export function relayHolderLine(
  row: WsParticipant,
  zone: string | null,
): string | null {
  if (!row.relay_members || row.status !== "playing") return null;
  if (!row.relay_holder) return "Baton free";
  if (!row.mod_connected) return `${row.relay_holder} offline`;
  return zone ? `${row.relay_holder}, ${zone}` : row.relay_holder;
}

export type RelayMemberState =
  | "playing"
  | "waiting"
  | "out"
  | "ready"
  | "finished";

/** Where a member stands in their team: out (abandoned or disqualified,
 * whatever the team does), finished, the holder playing, ready (before the
 * start), else waiting for the baton. */
export function relayMemberState(
  member: RelayMember,
  holderId: string | null | undefined,
): RelayMemberState {
  if (member.status === "abandoned" || member.status === "disqualified") {
    return "out";
  }
  if (member.status === "finished") return "finished";
  if (holderId != null && member.participant_id === holderId) return "playing";
  if (member.status === "ready") return "ready";
  return "waiting";
}

/** The state as the unfolded list writes it; the holder and a waiting member
 * add ", offline" when they have no connection. */
export function relayMemberLabel(
  member: RelayMember,
  holderId: string | null | undefined,
): string {
  const state = relayMemberState(member, holderId);
  const offline =
    !member.online && (state === "playing" || state === "waiting");
  return offline ? `${state}, offline` : state;
}

/** The rules line of a relay race: zones in the seed, team size, and the cap
 * of a full team (a smaller team's cap is higher); each part is dropped when
 * the race does not give it. */
export function relayRuleLine(
  totalLayers: number | null | undefined,
  teamSize: number | null | undefined,
  cap: number | null | undefined,
): string {
  const parts: string[] = [];
  if (totalLayers) parts.push(`${totalLayers} zones`);
  if (teamSize) parts.push(`teams of ${teamSize}`);
  if (cap) {
    parts.push(
      `${cap} zones max per runner on a full team (higher on a smaller one)`,
    );
  }
  return `Relay: ${parts.join(", ")}.`;
}

/** The name of the runner who played a zone: the `runner_id` of the node's
 * last entry that is not a backtrack (a backtrack goes back to a zone already
 * played, so it says nothing about who played it). Null when the entry has no
 * runner or the runner is not among the members. */
export function relayRunnerAt(
  history: ZoneHistoryEntry[],
  nodeId: string,
  members: RelayMember[],
): string | null {
  for (let i = history.length - 1; i >= 0; i--) {
    const entry = history[i];
    if (entry.node_id !== nodeId || entry.type === "backtrack") continue;
    if (!entry.runner_id) return null;
    return (
      members.find((m) => m.participant_id === entry.runner_id)?.name ?? null
    );
  }
  return null;
}
