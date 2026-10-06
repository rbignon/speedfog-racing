/**
 * Every rectangle of every cast scene, in canvas coordinates.
 *
 * Three consumers derive from this module and none of them may carry a
 * coordinate of its own: the SVG mask that pierces the plate, the guides
 * mode that prints each hole's position, and the setup panel's table of OBS
 * source positions. A number typed anywhere else will drift from the other
 * two the first time the layout is touched.
 */

export const CANVAS = { w: 1920, h: 1080 } as const;

/** Page margin and the gutter between neighbouring rectangles. */
const M = 16;
const G = 16;

export interface Rect {
  x: number;
  y: number;
  w: number;
  h: number;
}

/** A hole: the plate is pierced here and OBS shows through. */
export type CastRole = "pov" | "hero" | "cam" | "map";

export interface CastRect extends Rect {
  id: string;
  role: CastRole;
  /** Human label, used by the guides mode and the setup panel. */
  label: string;
}

export interface CastScene {
  holes: CastRect[];
  /** Everything the page draws itself, keyed by name. */
  panels: Record<string, Rect>;
}

export type CastSceneId = "quad" | "focus" | "metro" | "duel" | "talk";

export interface SceneOptions {
  /** Which slot holds the hero POV on the focus scene (1 to 4). */
  focus?: number;
  /** How many caster cams the desk shows (0, 1 or 2). */
  cams?: number;
}

// --- the desk, shared by the quad, focus, duel and metro scenes ----------

const LOCK_W = 280;
const LOCK_GAP = 28;

/** A desk band along the canvas foot: two 4:3 cams at its full height, tight
 * around the lockup and centred, the race name and the clock filling the
 * sides. */
interface Desk {
  y: number;
  h: number;
  camW: number;
  cam1X: number;
  lockX: number;
  cam2X: number;
}

function desk(h: number): Desk {
  const camW = (h * 4) / 3;
  const cam1X = Math.round((CANVAS.w - (2 * camW + 2 * LOCK_GAP + LOCK_W)) / 2);
  const lockX = cam1X + camW + LOCK_GAP;
  return {
    y: CANVAS.h - M - h,
    h,
    camW,
    cam1X,
    lockX,
    cam2X: lockX + LOCK_W + LOCK_GAP,
  };
}

/** The full desk of the focus, duel and metro scenes: y 776, cams 384x288. */
const DESK = desk(288);
/** The quad's thinner desk, Ignite's pick (2026-10): y 848, cams 288x216.
 * Its four POVs were too small at a third of the canvas; they take the 72px
 * this desk gives up. Only the quad: the other scenes cannot grow their POVs
 * from it (the focus hero and the duel pair are bound by the width). */
const QUAD_DESK = desk(216);

/** Main area above a desk, kept 24px clear of it. */
const MAIN_Y = M;
function mainHeight(d: Desk): number {
  return d.y - 24 - MAIN_Y;
}
/** Above the full desk: y 16 to 752. */
const MAIN_H = mainHeight(DESK);

function deskHoles(cams: number, d: Desk = DESK): CastRect[] {
  const holes: CastRect[] = [];
  if (cams >= 1) {
    holes.push({
      id: "cam1",
      role: "cam",
      label: "CAM 1",
      x: d.cam1X,
      y: d.y,
      w: d.camW,
      h: d.h,
    });
  }
  if (cams >= 2) {
    holes.push({
      id: "cam2",
      role: "cam",
      label: "CAM 2",
      x: d.cam2X,
      y: d.y,
      w: d.camW,
      h: d.h,
    });
  }
  return holes;
}

function deskPanels(d: Desk = DESK): Record<string, Rect> {
  return {
    race: { x: M, y: d.y, w: d.cam1X - 2 * M, h: d.h },
    lockup: { x: d.lockX, y: d.y, w: LOCK_W, h: d.h },
    clock: {
      x: d.cam2X + d.camW + M,
      y: d.y,
      w: CANVAS.w - M - (d.cam2X + d.camW + M),
      h: d.h,
    },
  };
}

// --- scene 1, quad --------------------------------------------------------

// Two rows of 16:9 POVs fill the height above the quad's own desk; the cards
// take the width the POVs leave, so the row tiles the canvas edge to edge.
const POV_H = (mainHeight(QUAD_DESK) - G) / 2; // 396
const POV_W = (POV_H * 16) / 9; // 704
const CARD_W = (CANVAS.w - 2 * M - 2 * POV_W - 3 * G) / 2; // 216
const COL_L_CARD = M;
const COL_L_POV = COL_L_CARD + CARD_W + G;
const COL_R_POV = COL_L_POV + POV_W + G;
const COL_R_CARD = COL_R_POV + POV_W + G;
const ROW_Y = [MAIN_Y, MAIN_Y + POV_H + G];

/** Seat order: slot 1 top left, 2 top right, 3 bottom left, 4 bottom right. */
const SEATS = [
  { povX: COL_L_POV, cardX: COL_L_CARD, row: 0, mirrored: false },
  { povX: COL_R_POV, cardX: COL_R_CARD, row: 0, mirrored: true },
  { povX: COL_L_POV, cardX: COL_L_CARD, row: 1, mirrored: false },
  { povX: COL_R_POV, cardX: COL_R_CARD, row: 1, mirrored: true },
];

/** Where slot `n` (1-based) puts its card on the quad scene, and which way it faces. */
export function quadSeat(slot: number): {
  card: Rect;
  mirrored: boolean;
} {
  const seat = SEATS[slot - 1];
  return {
    card: { x: seat.cardX, y: ROW_Y[seat.row], w: CARD_W, h: POV_H },
    mirrored: seat.mirrored,
  };
}

function quadScene(cams: number): CastScene {
  const holes: CastRect[] = SEATS.map((seat, i) => ({
    id: `pov${i + 1}`,
    role: "pov" as const,
    label: `POV ${i + 1}`,
    x: seat.povX,
    y: ROW_Y[seat.row],
    w: POV_W,
    h: POV_H,
  }));
  const panels: Record<string, Rect> = { ...deskPanels(QUAD_DESK) };
  for (let slot = 1; slot <= 4; slot++) {
    panels[`card${slot}`] = quadSeat(slot).card;
  }
  return { holes: [...holes, ...deskHoles(cams, QUAD_DESK)], panels };
}

// --- scene 2, focus -------------------------------------------------------

// The hero's runner card sits left of the hero hole, so the eye reads
// card -> hero -> the small POVs, left to right across the scene.
const FOCUS_PANEL: Rect = { x: M, y: MAIN_Y, w: 240, h: MAIN_H };
const HERO: Rect = {
  x: FOCUS_PANEL.x + FOCUS_PANEL.w + G,
  y: MAIN_Y,
  w: 1296,
  h: 729,
};
const SMALL_W = 320; // a sixth of the canvas width
const SMALL_H = 180;
const SMALL_X = 1584;
const SMALL_Y = [MAIN_Y, MAIN_Y + SMALL_H + G, MAIN_Y + 2 * (SMALL_H + G)];
const FOCUS_STANDINGS: Rect = { x: SMALL_X, y: 604, w: SMALL_W, h: 148 };

function focusScene(focus: number, cams: number): CastScene {
  const heroSlot = Math.min(4, Math.max(1, Math.trunc(focus) || 1));
  const others = [1, 2, 3, 4].filter((s) => s !== heroSlot);
  const holes: CastRect[] = [
    {
      id: `pov${heroSlot}`,
      role: "hero",
      label: `HERO (POV ${heroSlot})`,
      ...HERO,
    },
    ...others.map((slot, i) => ({
      id: `pov${slot}`,
      role: "pov" as const,
      label: `POV ${slot}`,
      x: SMALL_X,
      y: SMALL_Y[i],
      w: SMALL_W,
      h: SMALL_H,
    })),
  ];
  return {
    holes: [...holes, ...deskHoles(cams)],
    panels: { ...deskPanels(), focus: FOCUS_PANEL, standings: FOCUS_STANDINGS },
  };
}

// --- scene 3, duel --------------------------------------------------------

// Two runners at the biggest 16:9 the main area fits side by side, and a
// strip beneath them reading card, versus block, card: each runner's card
// under their own POV, the head-to-head numbers between them.
const DUEL_POV_W = 928;
const DUEL_POV_H = 522; // 16:9 of 928
const DUEL_POV2_X = CANVAS.w - M - DUEL_POV_W;
const DUEL_STRIP_Y = MAIN_Y + DUEL_POV_H + G;
const DUEL_STRIP_H = MAIN_Y + MAIN_H - DUEL_STRIP_Y;
const DUEL_CARD_W = 436; // same width as the talk scene's race cards
const DUEL_VS_X = M + DUEL_CARD_W + G;
const DUEL_VS_W = CANVAS.w - M - DUEL_CARD_W - G - DUEL_VS_X;

function duelScene(cams: number): CastScene {
  const holes: CastRect[] = [
    {
      id: "pov1",
      role: "pov",
      label: "POV 1",
      x: M,
      y: MAIN_Y,
      w: DUEL_POV_W,
      h: DUEL_POV_H,
    },
    {
      id: "pov2",
      role: "pov",
      label: "POV 2",
      x: DUEL_POV2_X,
      y: MAIN_Y,
      w: DUEL_POV_W,
      h: DUEL_POV_H,
    },
  ];
  return {
    holes: [...holes, ...deskHoles(cams)],
    panels: {
      ...deskPanels(),
      duel1: { x: M, y: DUEL_STRIP_Y, w: DUEL_CARD_W, h: DUEL_STRIP_H },
      versus: { x: DUEL_VS_X, y: DUEL_STRIP_Y, w: DUEL_VS_W, h: DUEL_STRIP_H },
      duel2: {
        x: CANVAS.w - M - DUEL_CARD_W,
        y: DUEL_STRIP_Y,
        w: DUEL_CARD_W,
        h: DUEL_STRIP_H,
      },
    },
  };
}

// --- scene 4, metro -------------------------------------------------------

const MAP: Rect = { x: M, y: MAIN_Y, w: CANVAS.w - 2 * M, h: 482 };
const METRO_LOG: Rect = { x: M, y: 522, w: 900, h: 230 };
const METRO_STANDINGS: Rect = { x: 932, y: 522, w: 972, h: 230 };

function metroScene(cams: number): CastScene {
  // The map is drawn by the page, not pierced: it is listed as a hole only so
  // the guides mode prints its box. It carries no video, so it may sit under
  // nothing and overlap nothing.
  return {
    holes: [
      { id: "map", role: "map", label: "METRO MAP", ...MAP },
      ...deskHoles(cams),
    ],
    panels: {
      ...deskPanels(),
      log: METRO_LOG,
      standings: METRO_STANDINGS,
    },
  };
}

// --- scene 5, talk --------------------------------------------------------

const TALK_CAM_W = 736;
const TALK_CAM_H = 552; // 4:3
const TALK_LOCK_W = 360;
const TALK_Y = 76;
const TALK_CAM1_X = Math.round(
  (CANVAS.w - (2 * TALK_CAM_W + 2 * LOCK_GAP + TALK_LOCK_W)) / 2,
);
const TALK_LOCK_X = TALK_CAM1_X + TALK_CAM_W + LOCK_GAP;
const TALK_CAM2_X = TALK_LOCK_X + TALK_LOCK_W + LOCK_GAP;
const EVE_Y = 652;
const EVE_H = CANVAS.h - M - EVE_Y;
const RACE_CARD_W = 436;
const TALK_SEP_X = 1388;

function talkScene(cams: number): CastScene {
  const holes: CastRect[] = [];
  if (cams >= 1) {
    holes.push({
      id: "cam1",
      role: "cam",
      label: "CAM 1",
      x: TALK_CAM1_X,
      y: TALK_Y,
      w: TALK_CAM_W,
      h: TALK_CAM_H,
    });
  }
  if (cams >= 2) {
    holes.push({
      id: "cam2",
      role: "cam",
      label: "CAM 2",
      x: TALK_CAM2_X,
      y: TALK_Y,
      w: TALK_CAM_W,
      h: TALK_CAM_H,
    });
  }
  const panels: Record<string, Rect> = {
    topline: { x: M, y: M, w: CANVAS.w - 2 * M, h: 44 },
    lockup: { x: TALK_LOCK_X, y: TALK_Y, w: TALK_LOCK_W, h: TALK_CAM_H },
    separator: { x: TALK_SEP_X, y: EVE_Y, w: 1, h: EVE_H },
    standings: { x: 1420, y: EVE_Y, w: 484, h: EVE_H },
  };
  for (let i = 0; i < 3; i++) {
    panels[`race${i + 1}`] = {
      x: M + i * (RACE_CARD_W + G),
      y: EVE_Y,
      w: RACE_CARD_W,
      h: EVE_H,
    };
  }
  return { holes, panels };
}

/** The layout of one scene. `focus` and `cams` default to slot 1 and two cams. */
export function sceneLayout(
  scene: CastSceneId,
  opts: SceneOptions = {},
): CastScene {
  const cams = Math.min(2, Math.max(0, Math.trunc(opts.cams ?? 2)));
  switch (scene) {
    case "quad":
      return quadScene(cams);
    case "focus":
      return focusScene(opts.focus ?? 1, cams);
    case "metro":
      return metroScene(cams);
    case "duel":
      return duelScene(cams);
    case "talk":
      return talkScene(cams);
  }
}

/** The line the guides mode prints over a hole, and the setup panel tabulates. */
export function formatGeo(rect: CastRect): string {
  return `${rect.label}  ${rect.x},${rect.y}  ${rect.w}x${rect.h}`;
}

/**
 * Which of a scene's holes the plate should actually pierce: never the map
 * (the page draws it itself), and, when the caller says which POV/hero
 * slots hold a seated runner, only those. A `pov`/`hero` hole's id is always
 * `pov<slot>`, so the slot number comes straight off it. `seatedSlots`
 * omitted (metro, talk, or a caller that hasn't resolved seating yet) keeps
 * every non-map hole, so a scene with no POV holes needs no change to keep
 * working. Otherwise a race with fewer than four runners would still
 * broadcast a framed, numbered hole onto whatever sits under the browser
 * source, with nothing seated in it.
 */
export function pierceableHoles(
  holes: CastRect[],
  seatedSlots?: number[],
): CastRect[] {
  return holes.filter((h) => {
    if (h.role === "map") return false;
    if (seatedSlots && (h.role === "pov" || h.role === "hero")) {
      return seatedSlots.includes(Number(h.id.slice(3)));
    }
    return true;
  });
}

/**
 * An SVG mask that paints the whole canvas white except the holes, so the
 * plate below shows everywhere but there.
 */
export function maskDataUri(holes: CastRect[]): string {
  const cut = holes
    .map((h) => `<rect x='${h.x}' y='${h.y}' width='${h.w}' height='${h.h}'/>`)
    .join("");
  const svg =
    `<svg xmlns='http://www.w3.org/2000/svg' width='${CANVAS.w}' height='${CANVAS.h}'>` +
    `<defs><mask id='m'><rect width='100%' height='100%' fill='white'/>` +
    `<g fill='black'>${cut}</g></mask></defs>` +
    `<rect width='100%' height='100%' fill='white' mask='url(%23m)'/></svg>`;
  return `url("data:image/svg+xml,${svg.replace(/#/g, "%23").replace(/"/g, "'")}")`;
}
