/**
 * Relay races: teams of runners share one run, one playing at a time.
 */

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
