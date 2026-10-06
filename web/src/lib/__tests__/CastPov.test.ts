import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import CastPov from "$lib/components/cast/CastPov.svelte";

const baseProps = {
  rect: { x: 312, y: 16, w: 640, h: 360 },
  participant: null,
  slot: 2,
  nameplate: false,
};

describe("CastPov: slot chip", () => {
  // The slot number is a setup aid, matching an OBS source to its hole: on
  // air it would sit beside the runner's rank, a second number per runner.
  it("keeps the slot number off the live scene", () => {
    const { container } = render(CastPov, { props: baseProps });
    expect(container.querySelector(".slot")).toBeNull();
  });

  it("numbers the hole in guides mode", () => {
    const { container } = render(CastPov, {
      props: { ...baseProps, guides: true },
    });
    expect(container.querySelector(".slot")?.textContent).toBe("2");
  });
});
