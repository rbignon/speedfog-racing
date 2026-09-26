/**
 * How many rows fit inside a panel of a given height, and which of a list's
 * items to actually show once they don't. Shared by every cast panel that
 * lists a variable-length field (player standings, race results): a panel's
 * rect is fixed (it cuts a hole in nothing, but it still can't grow past its
 * own box on the 1920x1080 canvas), while the field it lists is not, so the
 * row count has to come from the rect the panel was actually given rather
 * than a typed constant that could drift from it.
 *
 * `rectH`, `headerH` and `rowH` are all in canvas units, the same units
 * `Rect.h` already carries: the page's own outer scale-to-fit transform
 * never enters this math, so these numbers read directly off each panel's
 * own CSS (its title block's font-size and margins, its row height).
 */
export function rowCapacity(
  rectH: number,
  headerH: number,
  rowH: number,
): number {
  return Math.max(0, Math.floor((rectH - headerH) / rowH));
}

export interface RowPlan<T> {
  /** Items to actually render, in their original order. */
  visible: T[];
  /** Items left out; 0 when everything fit. Drives the "+ N more" line. */
  hiddenCount: number;
}

/**
 * Caps `items` to `capacity` rows. Once there isn't room for everything,
 * the last row is given up to the "+ N more" line (see `CastStandings`,
 * `CastMiniStandings`, `CastRoundStandings`, `CastRaceCard`), the same
 * phrasing the in-game overlay's own footer uses for the same situation
 * (`mod/src/dll/ui.rs`'s "+ N more", `footer_more` in `mod/src/core/format.rs`).
 */
export function planRows<T>(items: T[], capacity: number): RowPlan<T> {
  if (items.length <= capacity) {
    return { visible: items, hiddenCount: 0 };
  }
  const shown = Math.max(0, capacity - 1);
  return { visible: items.slice(0, shown), hiddenCount: items.length - shown };
}
