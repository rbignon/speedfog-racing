/**
 * Format a pool name for display: replace underscores with spaces and title-case.
 * e.g. "boss_shuffle" → "Boss Shuffle"
 */
export function formatPoolName(name: string): string {
  return name.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
}
