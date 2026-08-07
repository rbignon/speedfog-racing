/**
 * Layout and style constants for the metro DAG visualization.
 */

import type { DagNodeType } from "./types";

// =============================================================================
// Layout tuning
// =============================================================================

/** Padding around the SVG content (px). Accounts for rotated label overflow. */
export const PADDING = 90;

/** Minimum gap between layers (px) */
export const BASE_GAP = 80;

/** Extra px per weight unit for gap after a node (0 = uniform spacing) */
export const WEIGHT_SCALE = 0;

/** Horizontal space for the station itself (px) */
export const NODE_AREA = 20;

/** Vertical gap between nodes at the same layer (px) */
export const LAYER_SPACING_Y = 80;

// =============================================================================
// Node radii by type
// =============================================================================

export const NODE_RADIUS: Record<DagNodeType, number> = {
  start: 10,
  final_boss: 10,
  legacy_dungeon: 10,
  major_boss: 9,
  boss_arena: 7,
  mini_dungeon: 5,
};

// =============================================================================
// Node colors by type
// =============================================================================

export const NODE_COLORS: Record<DagNodeType, string> = {
  start: "#D4A844",
  mini_dungeon: "#8B8B8B",
  boss_arena: "#C0C0C0",
  major_boss: "#9B59B6",
  legacy_dungeon: "#D4A844",
  final_boss: "#D4A844",
};

// =============================================================================
// Background color (used for "hollow" shapes that punch through to the surface)
// =============================================================================

export const BG_COLOR = "#1a1a2e";

// =============================================================================
// Edge styling
// =============================================================================

export const EDGE_STROKE_WIDTH = 3;
export const EDGE_COLOR = "#D4A844";
export const EDGE_OPACITY = 0.6;

// =============================================================================
// Label styling
// =============================================================================

export const LABEL_MAX_CHARS = 15;
export const LABEL_FONT_SIZE = 11;
export const LABEL_COLOR = "#BBB";
export const LABEL_OFFSET_Y = 18;

// =============================================================================
// Player color palette (for future live tracking steps)
// =============================================================================

// Retuned toward the charter's navy/brass temperature (2026-08-07): same
// tier structure and hue slots as the original Tailwind-400 set, slightly
// desaturated and warmed; lemon pushed away from brass, violet away from
// fog, red away from ember. Mutual contrast validated on bundled 5px
// parallel traces and 3px rail borders.
export const PLAYER_COLORS = [
  // Tier 1: anchor hues, maximum mutual contrast
  "#45AEE0", // 0  sky blue
  "#E9718C", // 1  rose
  "#55CE82", // 2  green
  "#EE9550", // 3  orange
  "#9184E8", // 4  violet
  "#EFD35D", // 5  lemon
  // Tier 2: secondary hues, fill the gaps
  "#3EC4AE", // 6  teal
  "#D876E3", // 7  fuchsia
  "#D95C63", // 8  crimson
  "#A8D84C", // 9  lime
  // Tier 3: tertiary hues, intermediate positions
  "#7B87E8", // 10 indigo
  "#47C495", // 11 emerald
  "#E5B24A", // 12 amber
  "#E070AC", // 13 pink
  "#3FC3DE", // 14 cyan
  // Tier 4: lighter variants of anchors
  "#8CC8EE", // 15 light blue
  "#EDA2A2", // 16 light red
  "#92DFAC", // 17 light green
  "#EFB683", // 18 light orange
  "#ABA3EC", // 19 lavender
];

// =============================================================================
// Hero animation
// =============================================================================

/** Duration of the edge-drawing phase (ms) */
export const DRAW_PHASE_DURATION_MS = 2000;

/** Pause between draw phase completing and racers starting (ms) */
export const DRAW_TO_RACE_PAUSE_MS = 500;

/** Number of simulated racers in the hero animation */
export const HERO_RACER_COUNT = 4;

/** Radius of racer dot circles (px) */
export const RACER_DOT_RADIUS = 6;

/** Duration of one full racer loop (ms) */
export const RACE_LOOP_DURATION_MS = 8000;

/** Colors assigned to hero racers */
export const HERO_RACER_COLORS = PLAYER_COLORS.slice(0, 4);

// =============================================================================
// Parallel path spacing (results DAG)
// =============================================================================

/** Perpendicular spacing between parallel player lines on shared edges (px) */
export const PARALLEL_PATH_SPACING = 5;

/** Max parallel lines before extra players overlap at center */
export const MAX_PARALLEL = 5;

// =============================================================================
// Progressive reveal (adjacent/undiscovered nodes)
// =============================================================================

export const ADJACENT_NODE_COLOR = "#444";
export const ADJACENT_OPACITY = 0.25;
export const ADJACENT_EDGE_OPACITY = 0.15;
export const REVEAL_TRANSITION_MS = 300;

// =============================================================================
// Live overlay player dots
// =============================================================================

/** Orbit radius for live player dots (SVG px) */
export const LIVE_ORBIT_RADIUS = 9;

/** Orbit period for live dots (ms wall-clock) */
export const LIVE_ORBIT_PERIOD_MS = 2000;

/** Duration of skull pop-and-fade animation (ms) */
export const LIVE_SKULL_ANIM_MS = 1500;

/** Skull peak scale (overshoot) */
export const LIVE_SKULL_PEAK_SCALE = 2.0;

/** X offset for finished player dots right of final node (px) */
export const LIVE_FINISHED_X_OFFSET = 20;

/** X offset for setup player dots left of start node (px) */
export const LIVE_START_X_OFFSET = -20;
