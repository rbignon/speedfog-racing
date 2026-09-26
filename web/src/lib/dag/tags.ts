/**
 * Player tags: a runner drawn as a dot with a straight connector and their
 * name at its end, above or below the dot. Pure placement math, kept out of
 * LivePlayerDots so it can be tested without rendering.
 *
 * All lengths are graph units, the same space node coordinates live in.
 */

export interface TagPoint {
  id: string;
  /** Runners sharing a key sit at the same spot (a node, the start, the
   * finish) and are spread side by side instead of drawn on top of each
   * other. */
  key: string;
  x: number;
  y: number;
}

/**
 * Spreads runners that share a spot horizontally, centred on it, `spacing`
 * apart and in input order. A runner alone on its spot keeps its position.
 */
export function spreadColocated(
  points: TagPoint[],
  spacing: number,
): Map<string, { x: number; y: number }> {
  const groups = new Map<string, TagPoint[]>();
  for (const p of points) {
    const group = groups.get(p.key);
    if (group) group.push(p);
    else groups.set(p.key, [p]);
  }
  const result = new Map<string, { x: number; y: number }>();
  for (const group of groups.values()) {
    const mid = (group.length - 1) / 2;
    group.forEach((p, i) => {
      result.set(p.id, { x: p.x + (i - mid) * spacing, y: p.y });
    });
  }
  return result;
}

/** A tag's name box width, estimated from its length: SVG text can't be
 * measured before it renders, and a condensed display face averages about
 * half an em per character. Errs wide, so a tie counts as a collision. */
export function estimateNameWidth(name: string, fontSize: number): number {
  return name.length * fontSize * 0.52;
}

export interface TagAnchor {
  id: string;
  /** The dot's centre. */
  x: number;
  y: number;
  /** The name's estimated width. */
  width: number;
  /** The side this tag prefers when its dot sits on the window's middle,
   * where both sides have the same room. Keep it stable per runner, so a
   * tag doesn't flip because some other runner moved. */
  lean: -1 | 1;
}

export interface TagMetrics {
  /** Dot radius plus its ring: what another tag's name must not cover. */
  dotRadius: number;
  /** Distance from the dot's centre to the near edge of its name, at the
   * first tier. */
  reach: number;
  /** Height of a name box. */
  nameHeight: number;
  /** How much further out each extra tier pushes the name. */
  tierStep: number;
  /** Tiers tried in each direction before giving up and overlapping. */
  maxTiers: number;
}

export interface TagPlacement {
  /** -1 puts the name above the dot, 1 below. */
  dir: -1 | 1;
  /** Distance from the dot's centre to the name's near edge. */
  reach: number;
  /** Where the name is centred: the dot's own x, unless that would push
   * the name past the window's left or right edge. */
  nameX: number;
}

/** The part of the map on screen, in graph units. */
export interface TagView {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

interface Box {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

function overlaps(a: Box, b: Box): boolean {
  return (
    a.left < b.right && b.left < a.right && a.top < b.bottom && b.top < a.bottom
  );
}

/**
 * Chooses, for each tag, whether its name goes above or below the dot and
 * how far out, so that no name covers another name or another runner's dot,
 * and every name stays inside the visible window.
 *
 * Each tag prefers pointing toward the middle of the window, where there is
 * room; a dot on the middle itself follows its own `lean`. When the
 * preferred slot collides or would leave the window, the other direction is
 * tried at the same distance, then both again one tier further out. If
 * nothing is free within `maxTiers`, the first direction that stays inside
 * the window is kept and the overlap accepted: a tag is never dropped.
 *
 * A name near the window's left or right edge slides inward rather than
 * being cut, its connector still leaving from the dot. Tags are placed left
 * to right, so the result doesn't depend on the input order.
 */
export function placeTags(
  anchors: TagAnchor[],
  view: TagView,
  m: TagMetrics,
): Map<string, TagPlacement> {
  const EPS = 0.5;
  const mid = (view.top + view.bottom) / 2;
  const ordered = [...anchors].sort((a, b) => a.x - b.x || a.y - b.y);

  const dotBoxes = new Map<string, Box>(
    anchors.map((a) => [
      a.id,
      {
        left: a.x - m.dotRadius,
        right: a.x + m.dotRadius,
        top: a.y - m.dotRadius,
        bottom: a.y + m.dotRadius,
      },
    ]),
  );
  const placedNames: Box[] = [];
  const result = new Map<string, TagPlacement>();

  function nameCentre(a: TagAnchor): number {
    const half = a.width / 2;
    // A name wider than the window can't fit either way: keep it centred.
    if (view.right - view.left <= a.width) return (view.left + view.right) / 2;
    return Math.min(Math.max(a.x, view.left + half), view.right - half);
  }

  function nameBox(a: TagAnchor, dir: -1 | 1, reach: number): Box {
    const near = a.y + dir * reach;
    const far = a.y + dir * (reach + m.nameHeight);
    const cx = nameCentre(a);
    return {
      left: cx - a.width / 2,
      right: cx + a.width / 2,
      top: Math.min(near, far),
      bottom: Math.max(near, far),
    };
  }

  function inView(box: Box): boolean {
    return box.top >= view.top && box.bottom <= view.bottom;
  }

  for (const a of ordered) {
    let dirs: (-1 | 1)[];
    if (Math.abs(a.y - mid) < EPS) dirs = [a.lean, -a.lean as -1 | 1];
    else dirs = a.y < mid ? [1, -1] : [-1, 1];

    let chosen: { dir: -1 | 1; reach: number } | null = null;
    let chosenBox: Box | null = null;
    for (let tier = 0; tier < m.maxTiers && !chosen; tier++) {
      const reach = m.reach + tier * m.tierStep;
      for (const dir of dirs) {
        const box = nameBox(a, dir, reach);
        if (!inView(box)) continue;
        const hitsName = placedNames.some((b) => overlaps(box, b));
        const hitsDot = [...dotBoxes].some(
          ([id, b]) => id !== a.id && overlaps(box, b),
        );
        if (!hitsName && !hitsDot) {
          chosen = { dir, reach };
          chosenBox = box;
          break;
        }
      }
    }
    if (!chosen) {
      const dir = dirs.find((d) => inView(nameBox(a, d, m.reach))) ?? dirs[0];
      chosen = { dir, reach: m.reach };
      chosenBox = nameBox(a, dir, m.reach);
    }
    placedNames.push(chosenBox!);
    result.set(a.id, { ...chosen, nameX: nameCentre(a) });
  }
  return result;
}
