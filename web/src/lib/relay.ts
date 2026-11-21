/**
 * Relay races: teams of runners share one run, one playing at a time.
 */

/** Zones one runner may play: `ceil(total_layers / members) + 1`, as the
 * server computes it (a team with no active member counts as one). */
export function relayCap(totalLayers: number, activeMembers: number): number {
  return Math.ceil(totalLayers / Math.max(1, activeMembers)) + 1;
}

/** The cap on a runner's zones for a team size, as a sentence; null when the
 * pool gives no zone count. */
export function relayCapSentence(
  totalLayers: number | null | undefined,
  teamSize: number,
): string | null {
  if (!totalLayers || totalLayers <= 0) return null;
  return `${totalLayers} zones, teams of ${teamSize}: ${relayCap(totalLayers, teamSize)} zones max per runner.`;
}
