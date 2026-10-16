import { describe, expect, it } from "vitest";
import {
  buildObsCollection,
  duelPairs,
  holeRelative,
  type ObsExportInput,
  type ObsRunner,
} from "../cast/obs";
import { pierceableHoles, sceneLayout, type CastSceneId } from "../cast/layout";

type Obj = Record<string, any>; // eslint-disable-line @typescript-eslint/no-explicit-any

const runner = (username: string, name = username): ObsRunner => ({
  username,
  name,
});
const four = [runner("alice"), runner("bob"), runner("cleo"), runner("dan")];
const url = {
  cams: 2,
  raceId: "r1",
  casters: ["ann", null] as [string | null, string | null],
  delayS: 5,
  event: "season-one",
};

function input(over: Partial<ObsExportInput> = {}): ObsExportInput {
  return {
    origin: "https://speedfog.racing",
    collectionName: "Group G",
    seats: four,
    fieldSize: 4,
    url,
    includeTalk: true,
    ...over,
  };
}

const sourcesOf = (c: Obj): Obj[] => c.sources;
const scenesOf = (c: Obj): Obj[] =>
  sourcesOf(c).filter((s) => s.id === "scene");
const byName = (c: Obj, name: string): Obj => {
  const s = sourcesOf(c).find((x) => x.name === name);
  if (!s) throw new Error(`no source ${name}`);
  return s;
};

/** The layout id a scene was built from, read off its plate's URL. */
function sceneKind(
  c: Obj,
  scene: Obj,
): { id: CastSceneId; focus?: number } | null {
  const items: Obj[] = scene.settings.items;
  if (items.length === 0) return null;
  const top = items[items.length - 1];
  const plate = sourcesOf(c).find((s) => s.uuid === top.source_uuid);
  if (!plate || plate.id !== "browser_source") return null;
  const u = new URL(plate.settings.url);
  const id = u.pathname.split("/").pop() as CastSceneId;
  const focus = u.searchParams.get("focus");
  return { id, focus: focus ? Number(focus) : undefined };
}

describe("buildObsCollection", () => {
  it("every item references a source that exists", () => {
    const c = buildObsCollection(input());
    const uuids = new Set(sourcesOf(c).map((s) => s.uuid));
    for (const s of scenesOf(c)) {
      for (const it of s.settings.items)
        expect(uuids.has(it.source_uuid)).toBe(true);
    }
  });

  it("source names and uuids are unique", () => {
    const c = buildObsCollection(input());
    const names = sourcesOf(c).map((s) => s.name);
    const uuids = sourcesOf(c).map((s) => s.uuid);
    expect(new Set(names).size).toBe(names.length);
    expect(new Set(uuids).size).toBe(uuids.length);
    for (const u of uuids)
      expect(u).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/,
      );
  });

  it("every pierced hole holds exactly one item with its rect", () => {
    for (const seats of [four, [runner("alice"), null, runner("cleo"), null]]) {
      const c = buildObsCollection(input({ seats }));
      for (const s of scenesOf(c)) {
        const kind = sceneKind(c, s);
        if (!kind) continue;
        const holes = pierceableHoles(
          sceneLayout(kind.id, { cams: 2, focus: kind.focus }).holes,
          kind.id === "duel"
            ? [1, 2]
            : seats.flatMap((r, i) => (r ? [i + 1] : [])),
        );
        const holeItems = s.settings.items.filter(
          (it: Obj) => it.bounds_type === 3,
        );
        expect(holeItems).toHaveLength(holes.length);
        for (const h of holes) {
          const match = holeItems.filter(
            (it: Obj) =>
              it.pos.x === h.x &&
              it.pos.y === h.y &&
              it.bounds.x === h.w &&
              it.bounds.y === h.h,
          );
          expect(match).toHaveLength(1);
          expect(match[0].bounds_crop).toBe(true);
        }
      }
      expect(
        byName(c, "Metro").settings.items.filter(
          (it: Obj) => it.bounds_type === 3,
        ),
      ).toHaveLength(2);
    }
  });

  it("the plate is each cast scene's top item and Audio its bottom one", () => {
    const c = buildObsCollection(input());
    const castScenes = scenesOf(c).filter((s) => sceneKind(c, s));
    expect(castScenes.length).toBe(1 + 1 + 4 + 6 + 1 + 1);
    for (const s of castScenes) {
      const items: Obj[] = s.settings.items;
      expect(items[0].name).toBe("Audio");
      const plate = byName(c, `${s.name} plate`);
      expect(items[items.length - 1].source_uuid).toBe(plate.uuid);
      expect(plate.muted).toBe(true);
      expect(plate.volume).toBe(0);
      expect(plate.private_settings.mixer_hidden).toBe(true);
    }
  });

  it("relative coordinates match OBS's own", () => {
    const a = holeRelative({ x: 248, y: 16, w: 1, h: 1 });
    expect(a.pos_rel.x).toBeCloseTo(-1.3185185194015503, 6);
    expect(a.pos_rel.y).toBeCloseTo(-0.970370352268219, 6);
    expect(a.bounds_rel.x).toBeCloseTo(0.0018518518190830946, 6);
    expect(a.bounds_rel.y).toBeCloseTo(0.0018518518190830946, 6);
    const b = holeRelative({ x: 968, y: 428, w: 1, h: 1 });
    expect(b.pos_rel.x).toBeCloseTo(0.014814814552664757, 6);
    expect(b.pos_rel.y).toBeCloseTo(-0.2074074149131775, 6);
  });

  it("every seat is explicit in the plate URLs", () => {
    const c = buildObsCollection(
      input({ seats: [runner("alice"), runner("bob"), null, null] }),
    );
    expect(byName(c, "Quad plate").settings.url).toContain(
      "p1=alice&p2=bob&p3=-&p4=-",
    );
    const quad = byName(c, "Quad");
    const povItems = quad.settings.items.filter((it: Obj) =>
      it.name.startsWith("POV "),
    );
    expect(povItems.map((it: Obj) => it.name)).toEqual([
      "POV alice",
      "POV bob",
    ]);
  });

  it("a match collection names no race", () => {
    const c = buildObsCollection(
      input({
        url: {
          ...url,
          stageKeyed: true,
          eventSlug: "season-one",
          stageKey: "group_g",
        },
      }),
    );
    for (const s of sourcesOf(c)) {
      if (s.id !== "browser_source" || !s.name.endsWith(" plate")) continue;
      expect(s.settings.url).not.toContain("r1");
      expect(
        new URL(s.settings.url).pathname.startsWith(
          "/overlay/cast/event/season-one/group_g/",
        ),
      ).toBe(true);
    }
  });

  it("talk is first only when included, and current_scene follows", () => {
    const withTalk: Obj = buildObsCollection(input());
    expect(withTalk.scene_order[0].name).toBe("Talk");
    expect(withTalk.current_scene).toBe("Talk");
    expect(withTalk.current_program_scene).toBe("Talk");
    const without: Obj = buildObsCollection(input({ includeTalk: false }));
    expect(without.scene_order[0].name).toBe("Quad");
    expect(without.current_scene).toBe("Quad");
    expect(scenesOf(without).some((s) => s.name === "Talk")).toBe(false);
  });

  it("the same input builds the same file", () => {
    expect(buildObsCollection(input())).toEqual(buildObsCollection(input()));
  });

  it("colliding display names fall back to usernames", () => {
    const c = buildObsCollection(
      input({
        seats: [runner("ana_a", "Ana"), runner("ana_b", "ana"), null, null],
      }),
    );
    const names = sourcesOf(c).map((s) => s.name);
    expect(names).toContain("POV ana_a");
    expect(names).toContain("POV ana_b");
    expect(names).toContain("Focus: ana_a");
  });

  it("names keep spaces and accents", () => {
    const c = buildObsCollection(
      input({
        seats: [runner("elodie_r", "Élodie R"), null, null, null],
        url: { ...url, casters: ["ann marie", null] },
      }),
    );
    expect(sourcesOf(c).map((s) => s.name)).toContain("Focus: Élodie R");
    const u = new URL(byName(c, "Quad plate").settings.url);
    expect(u.searchParams.get("p1")).toBe("elodie_r");
    expect(byName(c, "Quad plate").settings.url).toContain("c1=ann%20marie");
  });
});

describe("duelPairs", () => {
  const seat = (n: number) => four.map((r, i) => (i < n ? r : null));
  it("covers every pair up to four runners", () => {
    expect(duelPairs(seat(4), 4)).toEqual([
      [1, 2],
      [1, 3],
      [1, 4],
      [2, 3],
      [2, 4],
      [3, 4],
    ]);
    expect(duelPairs(seat(3), 3)).toHaveLength(3);
    expect(duelPairs(seat(2), 2)).toHaveLength(1);
    expect(duelPairs(seat(1), 1)).toHaveLength(0);
  });
  it("keeps only slots 1 and 2 above four", () => {
    expect(duelPairs(seat(4), 6)).toEqual([[1, 2]]);
    expect(duelPairs([null, runner("bob"), null, null], 6)).toEqual([]);
  });
});
