import { describe, it, expect } from "vitest";
import { mapHighlightsToTimeline } from "../highlights";
import type { Highlight } from "$lib/highlights";
import type { ReplayParticipant } from "../types";

function makeHighlight(type: string, playerIds: string[]): Highlight {
  return {
    type,
    category: "competitive",
    title: type,
    segments: [{ type: "text", value: "test" }],
    playerIds,
    score: 50,
  };
}

function makeRP(
  id: string,
  visits: { nodeId: string; enterIgt: number; exitIgt: number }[],
): ReplayParticipant {
  return {
    id,
    displayName: id,
    color: "#fff",
    colorIndex: 0,
    zoneVisits: visits.map((v, i) => ({
      ...v,
      deaths: 0,
      deathTimestamps: [],
      isLast: i === visits.length - 1,
    })),
    totalIgt: visits.length > 0 ? visits[visits.length - 1].exitIgt : 0,
    finished: true,
    abandoned: false,
    finalBossNodeId: null,
  };
}

describe("mapHighlightsToTimeline", () => {
  it("maps photo_finish to the finish IGT of the involved players", () => {
    const rps = [
      makeRP("p1", [{ nodeId: "a", enterIgt: 0, exitIgt: 50000 }]),
      makeRP("p2", [{ nodeId: "a", enterIgt: 0, exitIgt: 52000 }]),
    ];
    const h = makeHighlight("photo_finish", ["p1", "p2"]);
    const events = mapHighlightsToTimeline([h], rps);
    expect(events).toHaveLength(1);
    // Should be at the later player's finish time
    expect(events[0].igtMs).toBe(52000);
  });

  it("maps global highlights to race midpoint", () => {
    const rps = [makeRP("p1", [{ nodeId: "a", enterIgt: 0, exitIgt: 100000 }])];
    const h = makeHighlight("same_brain", ["p1"]);
    const events = mapHighlightsToTimeline([h], rps);
    expect(events).toHaveLength(1);
    expect(events[0].igtMs).toBe(100000 / 2);
  });
});
