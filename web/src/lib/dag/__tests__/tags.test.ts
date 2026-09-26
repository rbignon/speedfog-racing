import { describe, it, expect } from "vitest";
import { placeTags, spreadColocated, type TagAnchor } from "../tags";

const METRICS = {
  dotRadius: 9,
  reach: 47,
  nameHeight: 19,
  tierStep: 22,
  maxTiers: 4,
};
// Nodes sit between 90 and 410 in a real layout; the view shows 84 to 416
// vertically and a 13-layer slice horizontally.
const VIEW = { left: 0, right: 1300, top: 84, bottom: 416 };

function anchor(
  id: string,
  x: number,
  y: number,
  lean: -1 | 1 = -1,
  width = 80,
): TagAnchor {
  return { id, x, y, width, lean };
}

describe("spreadColocated", () => {
  it("leaves a runner alone on their spot where they are", () => {
    const out = spreadColocated([{ id: "a", key: "n1", x: 100, y: 50 }], 18);
    expect(out.get("a")).toEqual({ x: 100, y: 50 });
  });

  it("spreads runners sharing a spot side by side, centred on it", () => {
    const out = spreadColocated(
      [
        { id: "a", key: "n1", x: 100, y: 50 },
        { id: "b", key: "n2", x: 300, y: 50 },
        { id: "c", key: "n1", x: 100, y: 50 },
        { id: "d", key: "n1", x: 100, y: 50 },
      ],
      18,
    );
    expect(out.get("a")).toEqual({ x: 82, y: 50 });
    expect(out.get("c")).toEqual({ x: 100, y: 50 });
    expect(out.get("d")).toEqual({ x: 118, y: 50 });
    expect(out.get("b")).toEqual({ x: 300, y: 50 });
  });
});

describe("placeTags", () => {
  it("points toward the middle of the view, where there is room", () => {
    const out = placeTags(
      [anchor("high", 100, 170), anchor("low", 500, 330)],
      VIEW,
      METRICS,
    );
    expect(out.get("high")).toMatchObject({ dir: 1, reach: 47 });
    expect(out.get("low")).toMatchObject({ dir: -1, reach: 47 });
  });

  it("keeps a middle-row tag on its own side when another runner leaves the row", () => {
    const row = [
      anchor("a", 100, 250, -1),
      anchor("b", 500, 250, 1),
      anchor("c", 900, 250, -1),
    ];
    const full = placeTags(row, VIEW, METRICS);
    expect(full.get("a")!.dir).toBe(-1);
    expect(full.get("b")!.dir).toBe(1);
    expect(full.get("c")!.dir).toBe(-1);
    const withoutB = placeTags([row[0], row[2]], VIEW, METRICS);
    expect(withoutB.get("c")!.dir).toBe(-1);
  });

  it("gives runners side by side on the middle opposite sides, then a tier out", () => {
    // Same lean for all four: collisions alone decide.
    const out = placeTags(
      [
        anchor("a", 73, 250),
        anchor("b", 91, 250),
        anchor("c", 109, 250),
        anchor("d", 127, 250),
      ],
      VIEW,
      METRICS,
    );
    expect(out.get("a")).toMatchObject({ dir: -1, reach: 47 });
    expect(out.get("b")).toMatchObject({ dir: 1, reach: 47 });
    expect(out.get("c")).toMatchObject({ dir: -1, reach: 69 });
    expect(out.get("d")).toMatchObject({ dir: 1, reach: 69 });
  });

  it("never sends a name out of the view, even when the other side is taken", () => {
    // Both on the top row: up would leave the view, so the second one is
    // pushed down a tier instead of flipping up.
    const out = placeTags(
      [anchor("a", 281, 90), anchor("b", 299, 90)],
      VIEW,
      METRICS,
    );
    expect(out.get("a")).toMatchObject({ dir: 1, reach: 47 });
    expect(out.get("b")).toMatchObject({ dir: 1, reach: 69 });
  });

  it("slides a name inward at the view's side edges, and centres it on its dot elsewhere", () => {
    const out = placeTags(
      [
        anchor("left", 10, 170),
        anchor("inside", 600, 170),
        anchor("right", 1290, 170),
      ],
      VIEW,
      METRICS,
    );
    expect(out.get("left")!.nameX).toBe(40);
    expect(out.get("inside")!.nameX).toBe(600);
    expect(out.get("right")!.nameX).toBe(1260);
  });

  it("uses the slid position when checking collisions", () => {
    // b's dot is clear of a's centred name, but not of it once slid in.
    const out = placeTags(
      [anchor("a", 5, 250, -1), anchor("b", 70, 190)],
      VIEW,
      METRICS,
    );
    expect(out.get("a")!.nameX).toBe(40);
    expect(out.get("a")!.dir).toBe(1);
  });

  it("keeps a name off another runner's dot", () => {
    // Down from a is free of names but lands on b's dot, 60 below: up it is.
    const out = placeTags(
      [anchor("a", 500, 200), anchor("b", 500, 260)],
      VIEW,
      METRICS,
    );
    expect(out.get("a")).toMatchObject({ dir: -1, reach: 47 });
  });

  it("keeps every tag once there is no free slot, inside the view", () => {
    const crowd = Array.from({ length: 10 }, (_, i) =>
      anchor(`r${i}`, 100 + i, 90),
    );
    const out = placeTags(crowd, VIEW, { ...METRICS, maxTiers: 2 });
    expect(out.size).toBe(10);
    for (const placement of out.values()) expect(placement.dir).toBe(1);
  });

  it("doesn't depend on the order runners come in", () => {
    const anchors = [
      anchor("a", 73, 250),
      anchor("b", 91, 250, 1),
      anchor("c", 400, 170),
      anchor("d", 400, 330),
    ];
    const forward = placeTags(anchors, VIEW, METRICS);
    const reversed = placeTags([...anchors].reverse(), VIEW, METRICS);
    expect(reversed).toEqual(forward);
  });
});
