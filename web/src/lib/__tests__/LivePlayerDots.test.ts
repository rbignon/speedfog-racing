import { describe, expect, it } from "vitest";
import { render } from "@testing-library/svelte";
import LivePlayerDots from "$lib/dag/LivePlayerDots.svelte";
import type { PositionedNode } from "$lib/dag/types";

function fakeNode(over: Partial<PositionedNode> = {}): PositionedNode {
  return {
    id: "n1",
    type: "mini_dungeon",
    displayName: "Some Zone",
    zones: [],
    layer: 1,
    tier: 1,
    weight: 1,
    x: 100,
    y: 100,
    ...over,
  };
}

function fakeParticipant(over: Record<string, unknown> = {}) {
  return {
    id: "p-1",
    twitch_username: "alice",
    twitch_display_name: "Alice",
    status: "abandoned",
    current_zone: "n1",
    current_layer: 1,
    igt_ms: 1000,
    death_count: 0,
    color_index: 0,
    mod_connected: false,
    zone_history: null,
    ...over,
  };
}

const nodeMap = new Map([["n1", fakeNode()]]);

// A runner's live dot sits on the map on every embed of LivePlayerDots (the
// race page, the plain /overlay/race/[id]/dag route, training, the metro
// cast scene): names beside the dots are reserved for the one caller with
// room for them. This pins the default-off contract so a future change to
// the prop's default doesn't silently print names over every strip-sized
// embed that has never shown one.
describe("LivePlayerDots: player tags", () => {
  it("draws plain dots and no names when playerTags is absent", () => {
    const { container } = render(LivePlayerDots, {
      props: {
        participants: [fakeParticipant()],
        nodeMap,
      },
    });
    expect(container.querySelector(".live-dot")).not.toBeNull();
    expect(container.querySelector(".tag-name")).toBeNull();
  });

  it("names each runner when playerTags is on", () => {
    const { container } = render(LivePlayerDots, {
      props: {
        participants: [fakeParticipant()],
        nodeMap,
        playerTags: true,
      },
    });
    expect(container.querySelector(".live-dot")).toBeNull();
    const label = container.querySelector(".tag-name");
    expect(label?.textContent).toBe("Alice");
  });

  it("puts runners sharing a node side by side, names on opposite sides", () => {
    const { container } = render(LivePlayerDots, {
      props: {
        participants: [
          fakeParticipant({ id: "p-1", status: "playing" }),
          fakeParticipant({
            id: "p-2",
            twitch_display_name: "Bob",
            status: "playing",
            color_index: 1,
          }),
        ],
        nodeMap,
        playerTags: true,
      },
    });
    const names = [...container.querySelectorAll(".tag-name")];
    const xs = names.map((t) => Number(t.getAttribute("x")));
    const ys = names.map((t) => Number(t.getAttribute("y")));
    expect(xs[0]).not.toBe(xs[1]);
    // One above the node, one below it.
    expect(Math.sign(ys[0] - 100)).toBe(-Math.sign(ys[1] - 100));
  });
});

describe("LivePlayerDots: the final node at the end of a race", () => {
  it("puts a finisher past a runner still fighting there, without overlap", () => {
    const finalMap = new Map([
      ["end", fakeNode({ id: "end", type: "final_boss", x: 500, y: 100 })],
    ]);
    const { container } = render(LivePlayerDots, {
      props: {
        participants: [
          fakeParticipant({
            id: "p-1",
            twitch_display_name: "Winner",
            status: "finished",
            current_zone: "end",
          }),
          fakeParticipant({
            id: "p-2",
            twitch_display_name: "Fighter",
            status: "playing",
            current_zone: "end",
            color_index: 1,
          }),
        ],
        nodeMap: finalMap,
        playerTags: true,
      },
    });
    const dotX = (name: string) =>
      Number(
        [...container.querySelectorAll(".tag-dot circle")]
          .find((c) => c.querySelector("title")?.textContent === name)
          ?.getAttribute("cx"),
      );
    // Dot radius plus ring, twice: the two rings must not overlap.
    expect(dotX("Winner") - dotX("Fighter")).toBeGreaterThanOrEqual(17.5);
  });
});
