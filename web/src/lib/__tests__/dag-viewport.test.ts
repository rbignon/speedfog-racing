import { describe, it, expect } from "vitest";
import { fitViewportToContainer } from "$lib/dag/viewport";

const base = {
  centerX: 1500,
  centerY: 180,
  visibleWidth: 1300,
  visibleHeight: 360,
};

describe("fitViewportToContainer", () => {
  it("leaves the viewport alone when no container shape is given", () => {
    expect(fitViewportToContainer(base, undefined, 360)).toEqual(base);
  });

  it("takes its height from the container's shape, so the map fills a strip", () => {
    const fitted = fitViewportToContainer(base, 1888 / 482, 360);
    expect(fitted.visibleWidth).toBe(1300);
    expect(fitted.visibleHeight).toBeCloseTo(1300 / (1888 / 482), 3);
  });

  it("keeps the centre, so the runners stay where the follow put them", () => {
    const fitted = fitViewportToContainer(base, 4, 360);
    expect(fitted.centerX).toBe(base.centerX);
    expect(fitted.centerY).toBe(base.centerY);
  });

  it("ignores a container shape that makes no sense", () => {
    expect(fitViewportToContainer(base, 0, 360)).toEqual(base);
    expect(fitViewportToContainer(base, Number.NaN, 360)).toEqual(base);
  });

  it("never zooms past the whole graph's height", () => {
    const fitted = fitViewportToContainer(base, 20, 360);
    expect(fitted.visibleHeight).toBeGreaterThanOrEqual(40);
  });
});
