/**
 * Shared utilities for training pages.
 */

import { formatPoolName } from "./format";

/**
 * Strip "training_" prefix and format the pool name for display.
 */
export function displayPoolName(poolName: string): string {
  return formatPoolName(poolName.replace(/^training_/, ""));
}

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
