import { describe, it, expect } from "vitest";
import {
  CANVAS,
  sceneLayout,
  formatGeo,
  pierceableHoles,
  type Rect,
  type CastSceneId,
} from "$lib/cast/layout";

const SCENES: CastSceneId[] = ["quad", "focus", "metro", "duel", "talk"];

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

  // A fractional coordinate would reach the mask, the guides and the OBS
  // table: a caster can only type whole pixels into a source's transform.
  it("puts every rectangle on whole pixels", () => {
    for (const scene of SCENES) {
      for (const cams of [0, 1, 2]) {
        const { holes, panels } = sceneLayout(scene, { cams });
        for (const r of [...holes, ...Object.values(panels)]) {
          for (const v of [r.x, r.y, r.w, r.h]) {
            expect(Number.isInteger(v)).toBe(true);
          }
        }
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

  it("seats the hero's runner card panel to the left of the hero hole", () => {
    const { holes, panels } = sceneLayout("focus", { focus: 1 });
    const hero = holes.find((h) => h.role === "hero")!;
    expect(panels.focus.x + panels.focus.w).toBeLessThanOrEqual(hero.x);
  });

  it("seats two runners side by side on the duel scene, the strip tiling beneath them", () => {
    const { holes, panels } = sceneLayout("duel");
    const povs = holes.filter((h) => h.role === "pov");
    expect(povs.map((h) => h.id)).toEqual(["pov1", "pov2"]);
    expect(povs[0].y).toBe(povs[1].y);
    expect(povs[0].w).toBe(povs[1].w);
    // The strip reads card, versus block, card, left to right, all of it
    // below the two POVs and above the desk band.
    expect(panels.duel1.x + panels.duel1.w).toBeLessThanOrEqual(
      panels.versus.x,
    );
    expect(panels.versus.x + panels.versus.w).toBeLessThanOrEqual(
      panels.duel2.x,
    );
    for (const p of [panels.duel1, panels.versus, panels.duel2]) {
      expect(p.y).toBeGreaterThanOrEqual(povs[0].y + povs[0].h);
      expect(p.y + p.h).toBeLessThanOrEqual(panels.race.y);
    }
  });

  // The quad's four POVs were too small at a third of the canvas, so its
  // desk alone is thinner and its POVs take the height the desk gives up;
  // the other race scenes keep the full desk.
  it("thins the desk on the quad scene alone, its POVs taking the height it frees", () => {
    const quad = sceneLayout("quad");
    const cam = (scene: CastSceneId) =>
      sceneLayout(scene).holes.find((h) => h.id === "cam1")!;
    for (const scene of ["focus", "duel", "metro"] as const) {
      expect(cam("quad").h).toBeLessThan(cam(scene).h);
      expect(sceneLayout(scene).panels.race.h).toBe(cam(scene).h);
    }
    expect(quad.panels.race.h).toBe(cam("quad").h);
    expect(cam("quad").w * 3).toBe(cam("quad").h * 4);
    const povs = quad.holes.filter((h) => h.role === "pov");
    for (const p of povs) expect(p.w * 9).toBe(p.h * 16);
    // The same 24px breath above the desk as the other scenes keep.
    const bottom = Math.max(...povs.map((p) => p.y + p.h));
    expect(quad.panels.race.y - bottom).toBe(24);
    const focus = sceneLayout("focus");
    expect(
      focus.panels.race.y - (focus.panels.focus.y + focus.panels.focus.h),
    ).toBe(24);
  });

  it("tiles the quad's cards and POVs edge to edge across the canvas", () => {
    const { holes, panels } = sceneLayout("quad");
    const row = [
      panels.card1,
      holes.find((h) => h.id === "pov1")!,
      holes.find((h) => h.id === "pov2")!,
      panels.card2,
    ];
    expect(row[0].x).toBe(16);
    for (let i = 1; i < row.length; i++) {
      expect(row[i].x).toBe(row[i - 1].x + row[i - 1].w + 16);
    }
    expect(row[3].x + row[3].w).toBe(CANVAS.w - 16);
    expect(panels.card1.h).toBe(row[1].h);
  });

  it("gives the metro scene one map hole and no POV", () => {
    const { holes } = sceneLayout("metro");
    expect(holes.filter((h) => h.role === "map")).toHaveLength(1);
    expect(holes.filter((h) => h.role === "pov")).toHaveLength(0);
  });
});

describe("formatGeo", () => {
  it("prints the label, the origin and the size the way OBS asks for them", () => {
    const rect = {
      id: "pov1",
      role: "pov" as const,
      label: "POV 1",
      x: 248,
      y: 16,
      w: 704,
      h: 396,
    };
    expect(formatGeo(rect)).toBe("POV 1  248,16  704x396");
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
