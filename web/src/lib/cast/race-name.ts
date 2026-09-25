/**
 * The desk's race-name panel, from the organizer-authored race name rather
 * than the routing-only event slot. `docs/EVENTS.md` has organizers name a
 * stage race "Semi B - Race 1 - Standard" for exactly this reason, so the
 * name is the intended display source, not something to re-derive from a
 * slot key meant for matching, not showing.
 */

/**
 * Up to three display lines split from a race name like
 * "Semi B - Race 1 - Standard". A name with fewer than two " - " separated
 * parts (no separator at all, the common case for a race outside an event)
 * falls back to the whole name on a single line, rather than a mostly-empty
 * panel.
 */
export function splitRaceName(name: string): string[] {
  const parts = name
    .split(" - ")
    .map((part) => part.trim())
    .filter((part) => part.length > 0);
  if (parts.length < 2) return [name.trim()];
  return parts.slice(0, 3);
}
