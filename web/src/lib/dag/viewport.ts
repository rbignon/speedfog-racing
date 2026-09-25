export interface DagViewport {
  centerX: number;
  centerY: number;
  visibleWidth: number;
  visibleHeight: number;
}

/** Below this the viewport would show a sliver and the labels would collide. */
const MIN_VISIBLE_HEIGHT = 40;

/**
 * Give a follow viewport the shape of the box it is drawn in.
 *
 * Without this the visible height is the whole graph's height, so the
 * rendered aspect ratio is whatever the seed happens to be and a wide, short
 * box either letterboxes the map or crops it. With it, a 1888x482 map area
 * shows a window of the same shape, which is what makes the zone labels
 * render at a readable size instead of under 7 pixels.
 *
 * The fitted height is clamped between MIN_VISIBLE_HEIGHT (never a sliver
 * too thin to read) and the graph's own height (never zoomed out past what
 * the map actually has to show).
 */
export function fitViewportToContainer(
  viewport: DagViewport,
  containerAspect: number | undefined,
  layoutHeight: number,
): DagViewport {
  if (
    containerAspect === undefined ||
    !Number.isFinite(containerAspect) ||
    containerAspect <= 0
  ) {
    return viewport;
  }
  const fitted = viewport.visibleWidth / containerAspect;
  const visibleHeight = Math.max(
    MIN_VISIBLE_HEIGHT,
    Math.min(fitted, Math.max(layoutHeight, MIN_VISIBLE_HEIGHT)),
  );
  return { ...viewport, visibleHeight };
}
