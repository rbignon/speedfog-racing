/**
 * Build an OBS scene collection (Scene Collection > Import) for the cast
 * scenes. Each scene is an opaque plate (a Browser Source of the scene's URL)
 * on top, with the runners' Twitch players, the caster cams and a browser
 * capture underneath, one per hole of the scene's layout. The boilerplate
 * fields mirror a collection saved by OBS 32.
 */

import {
  CANVAS,
  pierceableHoles,
  sceneLayout,
  type CastSceneId,
  type Rect,
} from "./layout";
import { EMPTY_SEAT } from "./params";
import { buildCastUrl, type CastUrlOpts } from "./urls";

/** A seated runner: Twitch login and display name. */
export interface ObsRunner {
  username: string;
  name: string;
}

export interface ObsExportInput {
  origin: string;
  collectionName: string;
  /** The four seats in slot order; null is an empty seat. */
  seats: (ObsRunner | null)[];
  fieldSize: number;
  url: Omit<CastUrlOpts, "slots" | "focus">;
  includeTalk: boolean;
}

/** Every pair of seated slots (1-based) a duel scene is built for. */
export function duelPairs(
  seats: (ObsRunner | null)[],
  fieldSize: number,
): [number, number][] {
  if (fieldSize > 4) return seats[0] && seats[1] ? [[1, 2]] : [];
  const pairs: [number, number][] = [];
  for (let a = 1; a <= 4; a++) {
    for (let b = a + 1; b <= 4; b++) {
      if (seats[a - 1] && seats[b - 1]) pairs.push([a, b]);
    }
  }
  return pairs;
}

export function twitchPlayerUrl(login: string): string {
  return `https://player.twitch.tv/?channel=${encodeURIComponent(login)}&parent=twitch.tv&player=popout`;
}

/** OBS's relative coordinates: units of half the canvas height, from its centre. */
export function holeRelative(r: Rect) {
  return {
    pos_rel: {
      x: (r.x - CANVAS.w / 2) / (CANVAS.h / 2),
      y: (r.y - CANVAS.h / 2) / (CANVAS.h / 2),
    },
    bounds_rel: { x: r.w / (CANVAS.h / 2), y: r.h / (CANVAS.h / 2) },
  };
}

/** Deterministic 128-bit hash of the text, formatted as a UUID. */
function uuidOf(text: string): string {
  const words: number[] = [];
  for (let seed = 0; seed < 4; seed++) {
    let h1 = 0xdeadbeef ^ (seed * 0x9e3779b1);
    let h2 = 0x41c6ce57 ^ (seed * 0x85ebca6b);
    for (let i = 0; i < text.length; i++) {
      const c = text.charCodeAt(i);
      h1 = Math.imul(h1 ^ c, 2654435761);
      h2 = Math.imul(h2 ^ c, 1597334677);
    }
    h1 =
      Math.imul(h1 ^ (h1 >>> 16), 2246822507) ^
      Math.imul(h2 ^ (h2 >>> 13), 3266489909);
    words.push(h1 >>> 0);
  }
  const hex = words.map((w) => w.toString(16).padStart(8, "0")).join("");
  return `${hex.slice(0, 8)}-${hex.slice(8, 12)}-${hex.slice(12, 16)}-${hex.slice(16, 20)}-${hex.slice(20, 32)}`;
}

type Obj = Record<string, unknown>;

const SCALE_REF = { x: CANVAS.w, y: CANVAS.h };

/** The fields every source carries, whatever its kind. */
function source(
  collection: string,
  name: string,
  id: string,
  settings: Obj,
  extra: Obj = {},
): Obj {
  return {
    prev_ver: 536870916,
    name,
    uuid: uuidOf(`${collection}\0${name}`),
    id,
    versioned_id: id,
    settings,
    mixers: id === "scene" ? 0 : 255,
    sync: 0,
    flags: 0,
    volume: 1.0,
    balance: 0.5,
    enabled: true,
    muted: false,
    "push-to-mute": false,
    "push-to-mute-delay": 0,
    "push-to-talk": false,
    "push-to-talk-delay": 0,
    hotkeys: {},
    deinterlace_mode: 0,
    deinterlace_field_order: 0,
    monitoring_type: 0,
    private_settings: {},
    ...extra,
  };
}

/** A scene holding the given items, bottom item first. */
function scene(collection: string, name: string, items: Obj[]): Obj {
  const hotkeys: Obj = { "OBSBasic.SelectScene": [] };
  for (const item of items) {
    hotkeys[`libobs.show_scene_item.${item.id}`] = [];
    hotkeys[`libobs.hide_scene_item.${item.id}`] = [];
  }
  return source(
    collection,
    name,
    "scene",
    { id_counter: items.length, custom_size: false, items },
    { hotkeys, canvas_uuid: "6c69626f-6273-4c00-9d88-c5136d61696e" },
  );
}

/** A scene item; with a rect it fills that hole (scaled to cover, cropped). */
function item(collection: string, id: number, name: string, rect?: Rect): Obj {
  const r = rect ?? { x: 0, y: 0, w: 0, h: 0 };
  const { pos_rel, bounds_rel } = holeRelative(r);
  return {
    name,
    source_uuid: uuidOf(`${collection}\0${name}`),
    visible: true,
    locked: true,
    rot: 0.0,
    scale_ref: SCALE_REF,
    align: 5,
    bounds_type: rect ? 3 : 0,
    bounds_align: 0,
    bounds_crop: rect !== undefined,
    crop_left: 0,
    crop_top: 0,
    crop_right: 0,
    crop_bottom: 0,
    id,
    group_item_backup: false,
    pos: { x: r.x, y: r.y },
    pos_rel,
    scale: { x: 1.0, y: 1.0 },
    scale_rel: { x: 1.0, y: 1.0 },
    bounds: { x: r.w, y: r.h },
    bounds_rel,
    scale_filter: "disable",
    blend_method: "default",
    blend_type: "normal",
    show_transition: { duration: 0 },
    hide_transition: { duration: 0 },
    private_settings: {},
  };
}

function browser(
  collection: string,
  name: string,
  url: string,
  plate: boolean,
): Obj {
  return source(
    collection,
    name,
    "browser_source",
    {
      url,
      width: CANVAS.w,
      height: CANVAS.h,
      ...(plate ? { reroute_audio: true } : {}),
    },
    {
      muted: true,
      ...(plate
        ? { volume: 0.0, private_settings: { mixer_hidden: true } }
        : {}),
    },
  );
}

export function buildObsCollection(
  input: ObsExportInput,
): Record<string, unknown> {
  const {
    origin,
    collectionName: C,
    seats,
    fieldSize,
    url,
    includeTalk,
  } = input;

  const runners = seats.filter((s): s is ObsRunner => s !== null);
  const lower = runners.map((r) => r.name.toLowerCase());
  const collides = lower.some((n, i) => lower.indexOf(n) !== i);
  const label = (r: ObsRunner) => (collides ? r.username : r.name);

  const sources: Obj[] = [];
  const sceneNames: string[] = [];
  const seen = new Set<string>();
  const add = (s: Obj) => {
    if (seen.has(s.name as string)) return;
    seen.add(s.name as string);
    sources.push(s);
  };

  const seatedAll = seats.flatMap((s, i) => (s ? [i + 1] : []));
  const slotsOf = (list: (ObsRunner | null)[]) =>
    list.map((s) => s?.username ?? EMPTY_SEAT);

  /**
   * One cast scene: Audio at the bottom, an item per pierced hole, the plate
   * on top. `holders` gives the runner under POV hole n.
   */
  const castScene = (
    name: string,
    id: CastSceneId,
    urlOpts: CastUrlOpts,
    seated: number[],
    holders: (ObsRunner | null)[],
    focus?: number,
  ) => {
    const plateName = `${name} plate`;
    const items: Obj[] = [item(C, 1, "Audio")];
    const layout = sceneLayout(id, { cams: url.cams, focus });
    for (const hole of pierceableHoles(layout.holes, seated)) {
      let holeSource: string;
      if (hole.role === "cam")
        holeSource = hole.id === "cam1" ? "Cam 1" : "Cam 2";
      else if (hole.role === "browser") holeSource = "Browser capture";
      else {
        const runner = holders[Number(hole.id.slice(3)) - 1];
        if (!runner) continue;
        holeSource = `POV ${label(runner)}`;
        add(browser(C, holeSource, twitchPlayerUrl(runner.username), false));
      }
      items.push(item(C, items.length + 1, holeSource, hole));
    }
    items.push(item(C, items.length + 1, plateName));
    add(browser(C, plateName, buildCastUrl(origin, id, urlOpts), true));
    add(scene(C, name, items));
    sceneNames.push(name);
  };

  if (includeTalk) {
    castScene("Talk", "talk", { ...url }, [], []);
  }
  castScene(
    "Quad",
    "quad",
    { ...url, slots: slotsOf(seats) },
    seatedAll,
    seats,
  );
  for (const slot of seatedAll) {
    castScene(
      `Focus: ${label(seats[slot - 1]!)}`,
      "focus",
      { ...url, slots: slotsOf(seats), focus: slot },
      seatedAll,
      seats,
      slot,
    );
  }
  for (const [a, b] of duelPairs(seats, fieldSize)) {
    const pair = [seats[a - 1], seats[b - 1]];
    castScene(
      `Duel: ${label(pair[0]!)} vs ${label(pair[1]!)}`,
      "duel",
      { ...url, slots: slotsOf(pair) },
      [1, 2],
      pair,
    );
  }
  castScene("Metro", "metro", { ...url }, seatedAll, seats);
  castScene("Browser", "browser", { ...url }, seatedAll, seats);

  // Placeholder scenes the caster fills with their own cams.
  for (const n of [1, 2].slice(0, url.cams)) {
    add(scene(C, `Cam ${n}`, []));
    sceneNames.push(`Cam ${n}`);
  }
  add(source(C, "Browser capture", "window_capture", {}));
  add(source(C, "Mic", "wasapi_input_capture", { device_id: "default" }));
  add(source(C, "Discord", "wasapi_process_output_capture", {}));
  add(source(C, "Music", "wasapi_process_output_capture", {}));
  add(
    scene(C, "Audio", [
      item(C, 1, "Mic"),
      item(C, 2, "Discord"),
      item(C, 3, "Music"),
    ]),
  );
  sceneNames.push("Audio");

  const first = sceneNames[0];
  return {
    name: C,
    current_scene: first,
    current_program_scene: first,
    scene_order: sceneNames.map((name) => ({ name })),
    sources,
    groups: [],
    quick_transitions: [
      { name: "Cut", duration: 300, hotkeys: [], id: 4, fade_to_black: false },
      { name: "Fade", duration: 300, hotkeys: [], id: 5, fade_to_black: false },
      { name: "Fade", duration: 300, hotkeys: [], id: 6, fade_to_black: true },
    ],
    transitions: [],
    saved_projectors: [],
    canvases: [],
    current_transition: "Fade",
    transition_duration: 300,
    preview_locked: false,
    scaling_enabled: false,
    scaling_level: -5,
    scaling_off_x: 0.0,
    scaling_off_y: 0.0,
    "virtual-camera": { type2: 3 },
    modules: {},
    version: 2,
  };
}
