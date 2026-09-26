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
  spotX = x,
): TagAnchor {
  return { id, x, y, width, lean, spotX };
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

describe("spreadColocated within the view", () => {
  const VIEW_X = { left: 0, right: 300 };
  const crowd = (x: number, n = 4) =>
    Array.from({ length: n }, (_, i) => ({
      id: `r${i}`,
      key: "start",
      x,
      y: 50,
    }));

  it("slides a crowd at the edge inward as a whole, keeping its spacing", () => {
    const out = spreadColocated(crowd(20), 18, VIEW_X, 10);
    expect(out.get("r0")!.x).toBe(10);
    expect(out.get("r3")!.x).toBe(64);
  });

  it("slides a crowd whose spot sits inside the margin just the same", () => {
    // No jump between a spot 5 from the edge and one a little further in.
    expect(spreadColocated(crowd(5), 18, VIEW_X, 10).get("r0")!.x).toBe(10);
  });

  it("leaves a group alone when it fits, and one whose spot is off the view", () => {
    const out = spreadColocated(
      [
        { id: "a", key: "n1", x: 150, y: 50 },
        { id: "b", key: "n1", x: 150, y: 50 },
        { id: "c", key: "n2", x: 400, y: 50 },
        { id: "d", key: "n2", x: 400, y: 50 },
      ],
      18,
      VIEW_X,
      10,
    );
    expect(out.get("a")!.x).toBe(141);
    expect(out.get("c")!.x).toBe(391);
  });

  it("centres a group too wide for the view", () => {
    const out = spreadColocated(crowd(20, 21), 18, VIEW_X, 10);
    expect((out.get("r0")!.x + out.get("r20")!.x) / 2).toBe(150);
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

  it("keeps every member of a group whose spot is on screen, past the edge too", () => {
    // Four runners on a node 10 inside the left edge, spread 18.5 apart.
    const out = placeTags(
      [
        anchor("a", -17.75, 170, -1, 80, 10),
        anchor("b", 0.75, 170, 1, 80, 10),
        anchor("c", 19.25, 170, -1, 80, 10),
        anchor("d", 37.75, 170, 1, 80, 10),
      ],
      VIEW,
      METRICS,
    );
    expect([...out.keys()].sort()).toEqual(["a", "b", "c", "d"]);
  });

  it("leaves out a runner whose spot is off the side of the view", () => {
    const out = placeTags(
      [
        anchor("before", -30, 170),
        anchor("in", 600, 170),
        anchor("after", 1400, 170),
      ],
      VIEW,
      METRICS,
    );
    expect([...out.keys()]).toEqual(["in"]);
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

  describe("with lanes past the graph's top and bottom rows", () => {
    const LANES = { top: 150, bottom: 350 };

    it("sends a name to the nearer lane, reaching past it", () => {
      const out = placeTags(
        [anchor("upper", 200, 230), anchor("lower", 700, 290)],
        VIEW,
        METRICS,
        LANES,
      );
      expect(out.get("upper")).toMatchObject({ dir: -1, reach: 80 });
      expect(out.get("lower")).toMatchObject({ dir: 1, reach: 60 });
    });

    it("keeps at least the usual reach for a dot already on the lane", () => {
      const out = placeTags([anchor("top", 200, 160)], VIEW, METRICS, LANES);
      expect(out.get("top")).toMatchObject({ dir: -1, reach: 47 });
    });

    it("stacks two names in the same lane rather than overlapping them", () => {
      const out = placeTags(
        [anchor("a", 200, 230), anchor("b", 220, 200)],
        VIEW,
        METRICS,
        LANES,
      );
      expect(out.get("a")).toMatchObject({ dir: -1, reach: 80 });
      expect(out.get("b")).toMatchObject({ dir: -1, reach: 50 + 22 });
    });

    it("never puts a name between another dot and that dot's own name", () => {
      // b sits on the top row, a below it in the same layer: a's name would
      // land right above b's dot, under b's own name, on the same vertical.
      const out = placeTags(
        [anchor("b", 500, 160), anchor("a", 500, 220)],
        VIEW,
        METRICS,
        LANES,
      );
      expect(out.get("b")).toMatchObject({ dir: -1, reach: 47 });
      expect(out.get("a")!.dir).toBe(1);
    });

    it("takes the other band when the nearer one is out of view", () => {
      const out = placeTags(
        [anchor("a", 200, 200)],
        { ...VIEW, top: 140 },
        METRICS,
        LANES,
      );
      expect(out.get("a")).toMatchObject({ dir: 1, reach: 150 });
    });

    it("falls back over the graph once both bands are full", () => {
      // Seven names side by side: three tiers fit in each band.
      const crowd = Array.from({ length: 7 }, (_, i) =>
        anchor(`r${i}`, 500 + i * 18.5, 250, i % 2 === 0 ? -1 : 1),
      );
      const out = placeTags(crowd, VIEW, METRICS, LANES);
      const boxes = crowd.map((a) => {
        const p = out.get(a.id)!;
        const near = a.y + p.dir * p.reach;
        const far = a.y + p.dir * (p.reach + METRICS.nameHeight);
        return {
          left: p.nameX - a.width / 2,
          right: p.nameX + a.width / 2,
          top: Math.min(near, far),
          bottom: Math.max(near, far),
        };
      });
      for (let i = 0; i < boxes.length; i++)
        for (let j = i + 1; j < boxes.length; j++) {
          const [p, q] = [boxes[i], boxes[j]];
          const clash =
            p.left < q.right &&
            q.left < p.right &&
            p.top < q.bottom &&
            q.top < p.bottom;
          expect(clash, `${i} and ${j}`).toBe(false);
        }
    });
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
