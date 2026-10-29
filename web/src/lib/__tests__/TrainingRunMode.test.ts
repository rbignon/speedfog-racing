import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import RunModeChip from "$lib/components/RunModeChip.svelte";
import { trainingMapView } from "$lib/utils/training";

describe("trainingMapView", () => {
  it("keeps an active speedrun session blind", () => {
    expect(trainingMapView({ mode: "speedrun" }, "active", true)).toBe(
      "progressive-only",
    );
    expect(trainingMapView({ mode: "speedrun" }, "active", false)).toBe(
      "hidden",
    );
  });

  it("gives the spoiler back once a speedrun session ends", () => {
    expect(trainingMapView({ mode: "speedrun" }, "finished", true)).toBe(
      "replay",
    );
    expect(trainingMapView({ mode: "speedrun" }, "abandoned", true)).toBe(
      "full",
    );
    expect(trainingMapView({ mode: "speedrun" }, "cancelled", true)).toBe(
      "full",
    );
  });

  it("keeps the spoiler for set seed and normal active sessions", () => {
    for (const mode of ["set_seed", "normal"]) {
      expect(trainingMapView({ mode }, "active", true)).toBe(
        "progressive-with-spoiler",
      );
      expect(trainingMapView({ mode }, "active", false)).toBe("structure");
    }
  });
});

describe("RunModeChip", () => {
  it("renders the mode text for ranked modes only", () => {
    expect(
      render(RunModeChip, { mode: "speedrun" }).container.textContent,
    ).toContain("Speedrun");
    expect(
      render(RunModeChip, { mode: "set_seed" }).container.textContent,
    ).toContain("Set Seed");
    expect(
      render(RunModeChip, { mode: "normal" }).container.textContent?.trim(),
    ).toBe("");
  });
});
