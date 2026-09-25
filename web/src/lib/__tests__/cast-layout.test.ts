import { describe, it, expect } from "vitest";
import {
  CANVAS,
  sceneLayout,
  formatGeo,
  pierceableHoles,
  type Rect,
  type CastSceneId,
} from "$lib/cast/layout";

const SCENES: CastSceneId[] = ["quad", "focus", "metro", "talk"];

function overlaps(a: Rect, b: Rect): boolean {
  return (
    a.x < b.x + b.w && b.x < a.x + a.w && a.y < b.y + b.h && b.y < a.y + a.h
  );
}

describe("sceneLayout", () => {
  it("keeps every rectangle inside the canvas", () => {
    for (const scene of SCENES) {
      const { holes, panels } = sceneLayout(scene);
      for (const r of [...holes, ...Object.values(panels)]) {
        expect(r.x).toBeGreaterThanOrEqual(0);
        expect(r.y).toBeGreaterThanOrEqual(0);
        expect(r.x + r.w).toBeLessThanOrEqual(CANVAS.w);
        expect(r.y + r.h).toBeLessThanOrEqual(CANVAS.h);
      }
    }
  });

  it("never overlaps two holes", () => {
    for (const scene of SCENES) {
      const { holes } = sceneLayout(scene);
      for (let i = 0; i < holes.length; i++) {
        for (let j = i + 1; j < holes.length; j++) {
          expect(overlaps(holes[i], holes[j])).toBe(false);
        }
      }
    }
  });

  it("never lets a panel sit over a hole", () => {
    for (const scene of SCENES) {
      const { holes, panels } = sceneLayout(scene);
      for (const panel of Object.values(panels)) {
        for (const hole of holes) {
          expect(overlaps(panel, hole)).toBe(false);
        }
      }
    }
  });

  it("seats four runners and two cams on the quad scene", () => {
    const { holes } = sceneLayout("quad");
    expect(holes.filter((h) => h.role === "pov")).toHaveLength(4);
    expect(holes.filter((h) => h.role === "cam")).toHaveLength(2);
  });

  it("drops the cam holes when the caster has no camera", () => {
    const { holes } = sceneLayout("quad", { cams: 0 });
    expect(holes.filter((h) => h.role === "cam")).toHaveLength(0);
    expect(holes.filter((h) => h.role === "pov")).toHaveLength(4);
  });

  it("keeps one cam hole, the left one, when only one caster is on camera", () => {
    const { holes } = sceneLayout("quad", { cams: 1 });
    const cams = holes.filter((h) => h.role === "cam");
    expect(cams).toHaveLength(1);
    expect(cams[0].id).toBe("cam1");
  });

  it("promotes the focused slot to the hero rectangle", () => {
    const { holes } = sceneLayout("focus", { focus: 3 });
    const hero = holes.find((h) => h.role === "hero");
    expect(hero?.id).toBe("pov3");
    expect(hero?.w).toBe(1296);
    const smalls = holes.filter((h) => h.role === "pov").map((h) => h.id);
    expect(smalls).toEqual(["pov1", "pov2", "pov4"]);
  });

  it("gives the metro scene one map hole and no POV", () => {
    const { holes } = sceneLayout("metro");
    expect(holes.filter((h) => h.role === "map")).toHaveLength(1);
    expect(holes.filter((h) => h.role === "pov")).toHaveLength(0);
  });
});

describe("formatGeo", () => {
  it("prints the label, the origin and the size the way OBS asks for them", () => {
    const rect = sceneLayout("quad").holes.find((h) => h.id === "pov1")!;
    expect(formatGeo(rect)).toBe("POV 1  312,16  640x360");
  });
});

describe("pierceableHoles", () => {
  it("never pierces the map hole, seatedSlots or not", () => {
    const { holes } = sceneLayout("metro");
    expect(pierceableHoles(holes).some((h) => h.role === "map")).toBe(false);
    expect(
      pierceableHoles(holes, [1, 2, 3, 4]).some((h) => h.role === "map"),
    ).toBe(false);
  });

  it("pierces every POV and cam hole when seatedSlots is omitted", () => {
    const { holes } = sceneLayout("quad");
    const pierced = pierceableHoles(holes);
    expect(pierced.filter((h) => h.role === "pov")).toHaveLength(4);
    expect(pierced.filter((h) => h.role === "cam")).toHaveLength(2);
  });

  it("leaves an unseated POV hole unpierced, but keeps the seated ones and the cams", () => {
    const { holes } = sceneLayout("quad");
    const pierced = pierceableHoles(holes, [1, 2, 4]);
    expect(pierced.map((h) => h.id).sort()).toEqual(
      ["cam1", "cam2", "pov1", "pov2", "pov4"].sort(),
    );
  });

  it("leaves the hero hole unpierced when its own slot has no seated runner", () => {
    const { holes } = sceneLayout("focus", { focus: 4 });
    const pierced = pierceableHoles(holes, [1, 2, 3]);
    expect(pierced.some((h) => h.id === "pov4")).toBe(false);
    expect(pierced.filter((h) => h.role === "pov")).toHaveLength(3);
  });
});
