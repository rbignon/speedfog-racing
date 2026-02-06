/**
 * Layout and style constants for the metro DAG visualization.
 */

import type { DagNodeType } from "./types";

// =============================================================================
// Layout tuning
// =============================================================================

/** Padding around the SVG content (px) — accounts for rotated label overflow */
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

export const LABEL_MAX_CHARS = 12;
export const LABEL_FONT_SIZE = 11;
export const LABEL_COLOR = "#999";
export const LABEL_OFFSET_Y = 20;

// =============================================================================
// Player color palette (for future live tracking steps)
// =============================================================================

export const PLAYER_COLORS = [
  "#C8A44E", // gold
  "#A78BFA", // purple
  "#2DD4BF", // teal
  "#FB7185", // rose
  "#38BDF8", // sky
  "#FB923C", // orange
  "#A3E635", // lime
  "#E879F9", // fuchsia
];
