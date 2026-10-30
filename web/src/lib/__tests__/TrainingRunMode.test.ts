import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import RunModeChip from "$lib/components/RunModeChip.svelte";
import { isBlindTrainingSession, trainingMapView } from "$lib/utils/training";

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

// The session page and its OBS overlay both follow this rule.
describe("isBlindTrainingSession", () => {
  it("hides an active speedrun session's map under either status name", () => {
    // The session detail says "active", the live connection "running".
    expect(isBlindTrainingSession({ mode: "speedrun" }, "active")).toBe(true);
    expect(isBlindTrainingSession({ mode: "speedrun" }, "running")).toBe(true);
  });

  it("shows the map once the run is over, and always for other modes", () => {
    for (const status of ["finished", "abandoned", "cancelled"]) {
      expect(isBlindTrainingSession({ mode: "speedrun" }, status)).toBe(false);
    }
    for (const mode of ["set_seed", "normal"]) {
      expect(isBlindTrainingSession({ mode }, "running")).toBe(false);
      expect(isBlindTrainingSession({ mode }, "active")).toBe(false);
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
