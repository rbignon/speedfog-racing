import type { Highlight } from "$lib/highlights";

/** Configuration constants for the replay animation */
export const REPLAY_DEFAULTS = {
  /** Total replay duration in ms (wall-clock) */
  DURATION_MS: 60_000,
  /** Orbit radius in SVG px when player is in a zone */
  ORBIT_RADIUS: 9,
  /** Orbit period in ms (wall-clock) — one full circle */
  ORBIT_PERIOD_MS: 2000,
  /** Duration of a skull pop-and-fade animation (ms) */
  SKULL_ANIM_MS: 600,
  /** Skull peak scale (overshoot) */
  SKULL_PEAK_SCALE: 1.3,
  /** Edge transition takes this fraction of the zone's replay time (rest is orbiting) */
  EDGE_TRANSIT_FRACTION: 0.15,
  /** Minimum transit duration in replay ms (so transitions aren't instant) */
  MIN_TRANSIT_MS: 200,
  /** Slow-mo speed multiplier during finish */
  FINISH_SLOWMO: 0.3,
  /** How long before max IGT the slow-mo kicks in (as fraction of total IGT) */
  FINISH_SLOWMO_THRESHOLD: 0.02,
  /** Commentary display duration (ms wall-clock) */
  COMMENTARY_DURATION_MS: 4000,
};

/** A single zone visit in the replay timeline */
export interface ReplayZoneVisit {
  nodeId: string;
  /** IGT when player entered this zone */
  enterIgt: number;
  /** IGT when player left (or race ended) */
  exitIgt: number;
  /** Deaths during this zone visit */
  deaths: number;
  /** IGT timestamps for individual death animations */
  deathTimestamps: number[];
  /** Was this the player's last zone? */
  isLast: boolean;
}

/** Pre-computed replay data for one participant */
export interface ReplayParticipant {
  id: string;
  displayName: string;
  color: string;
  colorIndex: number;
  zoneVisits: ReplayZoneVisit[];
  /** Total IGT for this participant */
  totalIgt: number;
  /** Did this participant finish the race? */
  finished: boolean;
  /** The node_id of the final_boss, if they reached it */
  finalBossNodeId: string | null;
}

/** Snapshot of a player's position at a given replay time */
export interface PlayerSnapshot {
  participantId: string;
  /** SVG x,y position */
  x: number;
  y: number;
  /** Current node the player is in/orbiting */
  currentNodeId: string;
  /** Is the player currently transitioning between nodes? */
  inTransit: boolean;
  /** Current layer (for leader computation) */
  layer: number;
}

/** A skull animation event */
export interface SkullEvent {
  nodeId: string;
  /** IGT timestamp when skull should appear */
  igtMs: number;
  /** Participant who died */
  participantId: string;
}

/** A commentary event tied to a timestamp */
export interface CommentaryEvent {
  /** IGT timestamp when commentary should appear */
  igtMs: number;
  /** The highlight that triggered this */
  highlight: Highlight;
}

/** Overall replay state */
export type ReplayState = "idle" | "playing" | "paused" | "finished";
