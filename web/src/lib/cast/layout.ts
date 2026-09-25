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

export type CastSceneId = "quad" | "focus" | "metro" | "talk";

export interface SceneOptions {
  /** Which slot holds the hero POV on the focus scene (1 to 4). */
  focus?: number;
  /** How many caster cams the desk shows (0, 1 or 2). */
  cams?: number;
}

// --- the desk, shared by the quad, focus and metro scenes -----------------

const BAND_H = 288;
const BAND_Y = CANVAS.h - M - BAND_H; // 776
const CAM_W = 384; // 4:3 at the band's height
const CAM_H = 288;
const LOCK_W = 280;
const LOCK_GAP = 28;
const CAM1_X = Math.round((CANVAS.w - (2 * CAM_W + 2 * LOCK_GAP + LOCK_W)) / 2);
const LOCK_X = CAM1_X + CAM_W + LOCK_GAP;
const CAM2_X = LOCK_X + LOCK_W + LOCK_GAP;

/** Main area above the desk: y 16 to 752. */
const MAIN_Y = M;
const MAIN_H = BAND_Y - 24 - MAIN_Y;

function deskHoles(cams: number): CastRect[] {
  const holes: CastRect[] = [];
  if (cams >= 1) {
    holes.push({
      id: "cam1",
      role: "cam",
      label: "CAM 1",
      x: CAM1_X,
      y: BAND_Y,
      w: CAM_W,
      h: CAM_H,
    });
  }
  if (cams >= 2) {
    holes.push({
      id: "cam2",
      role: "cam",
      label: "CAM 2",
      x: CAM2_X,
      y: BAND_Y,
      w: CAM_W,
      h: CAM_H,
    });
  }
  return holes;
}

function deskPanels(): Record<string, Rect> {
  return {
    race: { x: M, y: BAND_Y, w: CAM1_X - 2 * M, h: BAND_H },
    lockup: { x: LOCK_X, y: BAND_Y, w: LOCK_W, h: BAND_H },
    clock: {
      x: CAM2_X + CAM_W + M,
      y: BAND_Y,
      w: CANVAS.w - M - (CAM2_X + CAM_W + M),
      h: BAND_H,
    },
  };
}

// --- scene 1, quad --------------------------------------------------------

const POV_W = 640; // exactly a third of the canvas width
const POV_H = 360;
const CARD_W = 280; // 2 * CARD_W + 2 * POV_W = 1840, the canvas minus margins
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
  const panels: Record<string, Rect> = { ...deskPanels() };
  for (let slot = 1; slot <= 4; slot++) {
    panels[`card${slot}`] = quadSeat(slot).card;
  }
  return { holes: [...holes, ...deskHoles(cams)], panels };
}

// --- scene 2, focus -------------------------------------------------------

const HERO: Rect = { x: M, y: MAIN_Y, w: 1296, h: 729 };
const FOCUS_PANEL: Rect = { x: 1328, y: MAIN_Y, w: 240, h: MAIN_H };
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

// --- scene 3, metro -------------------------------------------------------

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

// --- scene 4, talk --------------------------------------------------------

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
    case "talk":
      return talkScene(cams);
  }
}

/** The line the guides mode prints over a hole, and the setup panel tabulates. */
export function formatGeo(rect: CastRect): string {
  return `${rect.label}  ${rect.x},${rect.y}  ${rect.w}x${rect.h}`;
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
