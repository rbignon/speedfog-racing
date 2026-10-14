import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import CastDuelCard from "$lib/components/cast/CastDuelCard.svelte";

const baseProps = {
  rect: { x: 16, y: 554, w: 436, h: 198 },
  rank: 1,
  avatarUrl: null,
  zoneNames: new Map<string, string>(),
  mirrored: false,
  leader: false,
  raceStatus: "running",
};

function fakeParticipant(over: Record<string, unknown> = {}) {
  return {
    id: "p-1",
    twitch_username: "alice",
    twitch_display_name: "Alice",
    status: "playing",
    current_zone: null,
    current_layer: 3,
    igt_ms: 90_000,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: null,
    gap_ms: null,
    equipped_badge_id: null,
    equipped_name_template_id: null,
    ...over,
  };
}

describe("CastDuelCard: states", () => {
  // The duel card has no Gap row to carry the state, so its zone line does,
  // still naming where the runner stopped.
  it.each([
    ["abandoned", "DNF"],
    ["disqualified", "DQ"],
  ])(
    "puts %s's state before the zone the runner stopped in",
    (status, text) => {
      const { container } = render(CastDuelCard, {
        props: {
          ...baseProps,
          participant: fakeParticipant({ status, current_zone: "zone_a" }),
          zoneNames: new Map([["zone_a", "Stormveil"]]),
        },
      });
      expect(container.querySelector(".dzone")?.textContent).toBe(
        `${text} · Stormveil`,
      );
    },
  );

  it("says DNF alone while the zone is not resolved", () => {
    const { container } = render(CastDuelCard, {
      props: {
        ...baseProps,
        participant: fakeParticipant({
          status: "abandoned",
          current_zone: "zone_a",
        }),
      },
    });
    expect(container.querySelector(".dzone")?.textContent).toBe("DNF");
  });

  it("reads Finished once the runner has finished", () => {
    const { container } = render(CastDuelCard, {
      props: {
        ...baseProps,
        participant: fakeParticipant({
          status: "finished",
          current_zone: "zone_a",
        }),
        zoneNames: new Map([["zone_a", "Stormveil"]]),
      },
    });
    const line = container.querySelector(".dzone");
    expect(line?.textContent).toBe("Finished");
    expect(line?.classList.contains("finished")).toBe(true);
  });

  it("shows the final time in the finished colour once the runner is done", () => {
    const { container } = render(CastDuelCard, {
      props: {
        ...baseProps,
        participant: fakeParticipant({ status: "finished", igt_ms: 3_725_000 }),
      },
    });
    const igt = container.querySelector(".digt");
    expect(igt?.textContent).toBe("1:02:05");
    expect(igt?.classList.contains("finished")).toBe(true);
  });

  it("leaves the zone line blank until the seed graph resolves the node id", () => {
    const { container } = render(CastDuelCard, {
      props: {
        ...baseProps,
        participant: fakeParticipant({ current_zone: "stormveil_48fd" }),
      },
    });
    expect(container.querySelector(".dzone")?.textContent).toBe("");
  });

  it("hands the whole resolved zone name to the CSS instead of pre-cutting it", () => {
    const { container } = render(CastDuelCard, {
      props: {
        ...baseProps,
        participant: fakeParticipant({ current_zone: "z1" }),
        zoneNames: new Map([["z1", "Promised Consort Radahn"]]),
      },
    });
    expect(container.querySelector(".dzone")?.textContent).toBe(
      "Promised Consort Radahn",
    );
  });
});

describe("CastDuelCard: before the start", () => {
  it("carries no rank and no leader brass", () => {
    const { container } = render(CastDuelCard, {
      props: {
        ...baseProps,
        leader: true,
        raceStatus: "setup",
        participant: fakeParticipant({ status: "ready" }),
      },
    });
    expect(container.querySelector(".drk")?.textContent ?? "").toBe("");
    expect(container.querySelector(".dcard.lead")).toBeNull();
  });
});

describe("CastDuelCard: stats", () => {
  it("leaves depth to the versus block beside it", () => {
    const { container } = render(CastDuelCard, {
      props: { ...baseProps, participant: fakeParticipant() },
    });
    const labels = [...container.querySelectorAll(".dk")].map(
      (el) => el.textContent,
    );
    expect(labels).not.toContain("Depth");
  });
});
