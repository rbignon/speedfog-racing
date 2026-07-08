/**
 * Parse leading dotted integer segments ("1.17.0" -> [1, 17, 0]).
 * Trailing non-numeric segments are ignored; returns null when no leading
 * numeric segment exists.
 *
 * The server has its own comparator (server/speedfog_racing/versioning.py)
 * with one deliberate difference: `isNewerVersion` pads missing segments
 * with zeros ("1.18" == "1.18.0"), while the server's tuple comparison
 * treats a missing segment as older. Keep any other semantic change in
 * sync between the two.
 */
export function parseVersion(value: string): number[] | null {
  const nums: number[] = [];
  for (const segment of value.trim().split(".")) {
    if (!/^\d+$/.test(segment)) break;
    nums.push(Number(segment));
  }
  return nums.length > 0 ? nums : null;
}

/** Whether `candidate` is strictly newer than `current`. */
export function isNewerVersion(candidate: string, current: string): boolean {
  const a = parseVersion(candidate);
  const b = parseVersion(current);
  if (!a || !b) return false;
  const len = Math.max(a.length, b.length);
  for (let i = 0; i < len; i++) {
    const x = a[i] ?? 0;
    const y = b[i] ?? 0;
    if (x !== y) return x > y;
  }
  return false;
}
