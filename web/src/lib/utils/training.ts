/**
 * Shared utilities for training pages.
 */

/**
 * Format IGT milliseconds as HH:MM:SS or MM:SS.
 */
export function formatIgt(ms: number): string {
  if (ms <= 0) return "--:--";
  const secs = Math.floor(ms / 1000);
  const mins = Math.floor(secs / 60);
  const hours = Math.floor(mins / 60);
  if (hours > 0) {
    return `${hours}:${String(mins % 60).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}`;
  }
  return `${String(mins).padStart(2, "0")}:${String(secs % 60).padStart(2, "0")}`;
}

export type TrainingMapView =
  | "replay"
  | "full"
  | "progressive-with-spoiler"
  | "progressive-only"
  | "hidden"
  | "structure";

/**
 * Which map the session page shows. A Speedrun-mode session stays blind while
 * ACTIVE: no full map, no spoiler toggle, no structure-only map. Once it is
 * not active the page behaves like any other session.
 */
export function trainingMapView(
  session: { mode: string },
  status: string,
  hasProgress: boolean,
): TrainingMapView {
  if (status === "finished" && hasProgress) return "replay";
  if ((status === "abandoned" || status === "cancelled") && hasProgress)
    return "full";
  if (status === "active") {
    const blind = session.mode === "speedrun";
    if (hasProgress)
      return blind ? "progressive-only" : "progressive-with-spoiler";
    if (blind) return "hidden";
  }
  return "structure";
}
