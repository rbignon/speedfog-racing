import { render } from "@testing-library/svelte";
import { describe, expect, it } from "vitest";
import Leaderboard from "$lib/components/Leaderboard.svelte";

function fakeParticipant(over: Record<string, unknown> = {}) {
  return {
    id: "p-1",
    twitch_username: "alice",
    twitch_display_name: "Alice",
    twitch_avatar_url: null,
    status: "finished",
    current_zone: null,
    current_layer: 0,
    igt_ms: 1500,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: [],
    daily_points: 50,
    ...over,
  };
}

describe("Leaderboard: +XX indicator (finished mode)", () => {
  it("renders +XX in the top-right slot when daily_points is set", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant({ daily_points: 33 })],
        mode: "finished",
        showRunDetails: true,
      },
    });
    const indicator = container.querySelector(".points-earned");
    expect(indicator?.textContent ?? "").toMatch(/\+33/);
  });

  it("does not render +XX when daily_points is null", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant({ daily_points: null })],
        mode: "finished",
        showRunDetails: true,
      },
    });
    const indicator = container.querySelector(".points-earned");
    expect(indicator).toBeNull();
  });

  it("renders +XX for a qualified abandoner and moves the layer to the Abandoned line", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [
          fakeParticipant({
            status: "abandoned",
            current_layer: 11,
            daily_points: 7,
          }),
        ],
        mode: "finished",
        totalLayers: 12,
        showRunDetails: true,
      },
    });
    // Points take the top-right slot, even for abandoners.
    expect(
      container.querySelector(".points-earned")?.textContent ?? "",
    ).toMatch(/\+7/);
    // The layer fraction is no longer in the top-right slot...
    expect(container.querySelector(".layer-fraction")).toBeNull();
    // ...it sits on the Abandoned line instead.
    expect(
      container.querySelector(".abandoned-label")?.textContent ?? "",
    ).toMatch(/Abandoned.*12\/12/s);
  });

  it("keeps the ✓ behavior in running mode", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant({ daily_points: null })],
        mode: "running",
        showRunDetails: true,
      },
    });
    const check = container.querySelector(".finish-icon");
    expect(check?.textContent ?? "").toContain("✓");
  });
});

describe("Leaderboard: Show all banner", () => {
  it("renders the banner when hasSelection is true", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant()],
        mode: "running",
        showRunDetails: true,
        selectedIds: new Set(["p-1"]),
        onClearSelection: () => {},
      },
    });
    expect(container.querySelector(".selection-banner")).not.toBeNull();
  });

  it("does not render the banner when selection is empty", () => {
    const { container } = render(Leaderboard, {
      props: {
        participants: [fakeParticipant()],
        mode: "running",
        showRunDetails: true,
        selectedIds: new Set<string>(),
        onClearSelection: () => {},
      },
    });
    expect(container.querySelector(".selection-banner")).toBeNull();
  });
});
